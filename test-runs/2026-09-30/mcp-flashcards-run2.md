稽核跑完了，全程唯讀，沒改任何檔案。下面是 auditor 的完整報告，原文照轉：

---

結論：我對 `<home>\work\tools\public\mcp-flashcards` 找到 3 個問題，1 個 High、2 個 Medium。整體寫得不錯，原子寫入、檔案鎖、讀檔失敗會報錯這些都有做到。問題集中在一點：出錯時模型收到的是「成功」，或者收到了不該看的東西。全程唯讀，沒有改任何檔案，也沒有執行 server。

## 稽核對象與 SDK 判定

- **範圍：** Python server，在範圍內，不是 TypeScript。進入點只有 `server.py`。
- **排除的檔案：** `.venv/` 是第三方套件，而且被 `.gitignore:7` 忽略。專案裡沒有測試、範例或 client 腳本。`README.md` 和 `.gitignore` 只拿來對照說明。
- **SDK 是 1.x：** `server.py:24` 的 `from mcp.server.fastmcp import FastMCP`。本機 venv 裝的是 `mcp-1.30.0`，跟規則基準一致。
- **傳輸是 stdio：** `server.py:206` 的 `mcp.run()`，沒有帶參數。
- **版本鎖定（R15）沒問題：** `requirements.txt:2` 的 `mcp>=1.2,<2`，1.x 的程式碼配 `<2`。

## 發現（嚴重度由高到低）

**1. High，R1：資料檔壞掉時，工具回報「牌組是空的」，而且標成成功**
`server.py:65-68`
```python
    except json.JSONDecodeError:
        ...
        DATA_FILE.replace(DATA_FILE.with_name(f"{DATA_FILE.name}.corrupt-{stamp}"))
        return _empty()
```
- **實際會發生什麼：** 把壞檔移到旁邊這件事本身是對的，資料不會丟。問題是 `_load()` 接著回傳一個假的空牌組，五個工具都當作正常情況處理：
  - `list_cards` 回 `{"ok": True, "count": 0, "cards": []}`（第 130 行）
  - `review` 回 "No cards to review"
  - `add_card` 從 #1 重新編號
  - 全部都是 `isError: false`，也沒有任何一個結果提到備份檔。

  所以模型會很有自信地告訴 Der「你沒有卡片」，而沒有人知道有一個 `.corrupt-` 備份在那裡。
- **Windows 上具體的觸發方式：** 內容完全正確、但開頭帶 UTF-8 BOM 的 JSON。例如用 Windows PowerShell 5.1 的 `Set-Content -Encoding UTF8` 產生的檔案。用 `encoding="utf-8"` 開檔時，`json.load` 會丟出 `JSONDecodeError("Unexpected UTF-8 BOM")`，一份好好的牌組就被移走了。
- **附帶一提：** 如果檔案是非 UTF-8 的位元組，會丟 `UnicodeDecodeError`，這裡沒有接。結果是大聲失敗，方向是安全的，只是跟 README 寫的 "Corrupt data is set aside" 對不上。
- **修法：** 保留移檔的動作，然後在這次呼叫直接報錯，並把 BOM 的情況一起處理掉。
  - 移檔後改成 `raise ToolError(f"cards.json was not valid JSON; moved it to {backup.name}. The deck is empty until you restore it.")`。`ToolError` 從 `mcp.server.fastmcp.exceptions` 匯入。訊息只放檔名，不要放完整路徑。
  - 第 63 行改用 `encoding="utf-8-sig"`，讓帶 BOM 的檔案可以正常讀進來。

**2. Medium，R1：用 id 找不到卡片，卻回報成功**
`server.py:172`（`grade_card`）和 `server.py:197`（`delete_card`）
```python
            return {"ok": False, "error": f"No card with id {card_id}"}
```
- **實際會發生什麼：** 這是用確切 id 查詢卻查不到，規則裡這種情況明確算問題。錯誤文字模型看得懂，但旗標是 `isError: false`。
  - 會依 `isError` 顯示錯誤的 client 不會標出來。
  - 模型也可能直接回報「已刪除」或「已記錄」。
  - `delete_card` 的 docstring（第 191 行）寫的是 "Returns an error"，但實際上回的不是錯誤。
- **修法：** 改成 `raise ToolError(f"No card with id {card_id}")`。訊息只重複 caller 自己給的值，沒有洩漏問題。`with _LOCK` 會自動釋放鎖。

**3. Medium，R4：檔案 I/O 錯誤會把完整路徑原樣傳給模型**
- **位置：**
  - `server.py:63`：`with DATA_FILE.open("r", encoding="utf-8") as f:`
  - `server.py:67`：`DATA_FILE.replace(...)`
  - `server.py:78`：`with tmp.open("w", encoding="utf-8") as f:`
  - `server.py:80`：`os.replace(tmp, DATA_FILE)`
- **影響範圍：** 五個工具都沒有 `try`，分別在第 94、120、134、162、189 行。
- **實際會發生什麼：** 在 1.x，未攔截的例外會被包成 `f"Error executing tool {self.name}: {e}"`（已在安裝版的 `mcp/server/fastmcp/tools/base.py:117` 確認），原樣送給模型。
  - README 自己提到的情境「被防毒或同步軟體鎖住」，在 Windows 上會變成 `[WinError 5] Access is denied: '<home>\\work\\tools\\public\\mcp-flashcards\\cards.json.tmp' -> '...cards.json'`。Windows 帳號名稱和資料夾結構都會露出來。
  - 1.x 在 server 端完全不記錄工具失敗，所以 operator 這邊查不到任何紀錄。
  - 值得肯定的是，這時確實是 `isError: true`，README 說的「讀檔失敗會報錯」有做到。
  - 沒有帳密外洩，所以評 Medium。
- **修法：** 在 `_load`/`_save` 裡把 I/O 包起來：`except OSError as e: logger.exception("cards.json I/O failed"); raise ToolError("Could not read or write cards.json (locked by another program or no permission); see server log") from e`。`logger` 用 `logging.getLogger(__name__)`，輸出到 stderr。

## 檢查過、沒有問題的規則

- **R15：** 版本鎖定正確，理由見上方。
- **R2：** 沒有 `McpError`。
- **R3：** 沒有手寫的參數檢查。參數都有型別（`str`/`int`/`bool`），SDK 會自己驗證。
- **R5：** 沒有 low-level handler。
- **R6：** 沒有 `CallToolResult`。回傳的 dict 用的是 `"ok"`，不是 `isError`/`is_error`。
- **R7：** stdio 模式下，沒有 `print`、`sys.stdout` 或導到 stdout 的 logging。
- **R9：** 沒有寫死的密鑰。
- **R10：** `DATA_FILE` 以 `__file__` 為基準（第 30 行），沒有寫死個人路徑。
- **R11：** 沒有由工具參數決定的檔案路徑。
- **R13：** 沒有 resource。
- **R1 的豁免情況：**
  - `review` 第 146 行的 `{"ok": False, "message": "No cards to review"}`，以及 `list_cards` 篩選後 0 筆，都屬於「篩選結果為 0 且明確說明」，規則豁免。
- **不適用：**
  - R8 和 R14 只適用 2.x。1.x 的同步工具本來就在 event loop 上依序執行，而且這裡也已經有鎖。
  - R12 只適用 HTTP，這個 server 走 stdio。

## 無法確認

- **BOM 的行為：** 「帶 BOM 會被當成壞檔」是依 CPython `json.loads` 的已知行為推論的。讀本機 `pythoncore-3.14-64\Lib\json\__init__.py` 時權限被拒，所以沒有對安裝版的 3.14.5 實際確認。
- **版本下限：** `>=1.2` 也允許 1.2 到 1.29，但規則只驗證過 1.30.0。全新安裝會抓 PyPI 上最新的 1.x，我沒有離線確認那一版是不是 1.30.x。發現 3 用到的例外包裝行為只在已安裝的 1.30.0 確認過。其他結論都不依賴版本相關的「Not a finding」條款。
- **Client 的顯示方式：** 發現 2 在各 client 上實際怎麼顯示 `ok: false` 但 `isError: false` 的結果，要看 client 的實作。

---

我建議先處理第 1 個。它是唯一會讓模型很有把握地講錯話的問題（跟你說「你沒有卡片」），而且在 Windows 上只要檔案開頭帶 BOM 就會觸發，不需要檔案真的壞掉。另外兩個修起來都只要幾行。

要我幫哪一個起草修法，或把哪個發現講得更細都可以，你說了我才會動檔案。
