稽核跑完了,全程唯讀,沒有改任何檔案。以下是 auditor 的報告原文:

---

結論:這支 server 大方向寫得很小心,有原子寫入、壞檔隔離、讀檔錯誤會往外丟,pin 也對。但我找到四個問題,最嚴重的是 cards.json 壞掉時,模型會以為牌組本來就是空的。整個過程唯讀,沒有改任何檔案,也沒有跑 server。

## Target and SDK detected

- **目標:** `<home>\work\tools\public\mcp-flashcards`。唯一的入口是 `server.py`,裡面有 5 個 high-level tool,沒有 resource、prompt 或 low-level handler。
- **排除的檔案:** `.venv\`(第三方套件,SDK 本身也在裡面)。專案裡沒有 tests、examples 或 client script。
- **SDK:** 1.x。證據是 `server.py:24` `from mcp.server.fastmcp import FastMCP`。
- **Transport:** stdio。證據是 `server.py:206` `mcp.run()`。
- **Pin(R15):** `requirements.txt:2` 寫 `mcp>=1.2,<2`,1.x 程式碼配 `<2`,正確。venv 裡裝的是 `mcp-1.30.0`,剛好是規則的 baseline,1.30 的規則可以直接套。專案沒有 lock file。
- 不是 TypeScript,在範圍內。

## Findings

### 1. High · R1 · `server.py:65-68`:壞掉的 cards.json 被當成空牌組,還回報成功

```python
    except json.JSONDecodeError:
        ...
        DATA_FILE.replace(DATA_FILE.with_name(f"{DATA_FILE.name}.corrupt-{stamp}"))
        return _empty()
```

`_load()` 遇到不合法的 JSON,會先把檔案改名成 `.corrupt-<時間>` 備份,再回傳空 store。五個 tool 都把這個空 store 當正常資料:
- `list_cards` 回 `{"ok": True, "count": 0, "cards": []}`
- `add_card` 回 `Added card #1`,ID 從 1 重新開始
- 全部都是 `isError: false`

資料其實還在磁碟上,但模型跟你都收不到「檔案壞了、已經備份」的訊號,只會看到牌組憑空消失。README 第 59 行寫「不會假裝牌組是空的」,這句只對權限錯誤和鎖檔錯誤成立,這條路不算。

觸發條件比想像中常見。Python 的 `json` 只要看到 UTF-8 BOM 就丟 `JSONDecodeError`("Unexpected UTF-8 BOM")。所以如果你用 PowerShell 5.1 的 `-Encoding UTF8` 或會加 BOM 的編輯器手改過 cards.json,一份完全讀得懂的檔案也會被隔離。

**修法:** 隔離機制留著,改名之後加一行 `raise ToolError(f"cards.json was not valid JSON and was moved to {backup.name}; nothing was changed. Call again to start a new deck.")`(`from mcp.server.fastmcp.exceptions import ToolError`)。第一次呼叫會帶 `isError: true` 把狀況講清楚,下一次找不到檔案,自然就從空牌組開始。另外讀檔改用 `encoding="utf-8-sig"`,有沒有 BOM 都能讀。

### 2. Medium · R1 · `server.py:172`:`grade_card` 找不到 ID 時回報成功

`return {"ok": False, "error": f"No card with id {card_id}"}`

用確切的 ID 查不到卡是失敗,但協定層送出去的是 `isError: false`。錯誤文字讀得懂,模型多半也看得懂 `ok: False`,但 client 不會把它當錯誤處理(實際表現看 client 而定),所以列 Medium。

**修法:** 改成 `raise ToolError(f"No card with id {card_id}")`。在 `with _LOCK:` 裡 raise 會正常釋放鎖。

### 3. Medium · R1 · `server.py:197`:`delete_card` 同樣的問題

一樣是 `return {"ok": False, "error": f"No card with id {card_id}"}`。第 191 行的 docstring 說 "Returns an error instead of crashing",但實際送出去的是成功旗標。修法跟上一條一樣,docstring 也順手改掉。

### 4. Medium · R4 · `server.py:63` / `:67` / `:80`:OS 錯誤原文連同完整路徑直接送給模型

出問題的是這三行:
- `with DATA_FILE.open("r", encoding="utf-8") as f:`(63)
- `DATA_FILE.replace(...)`(67)
- `os.replace(tmp, DATA_FILE)`(80)

五個 tool 都沒有 `try`,例如 `server.py:94` `def add_card(question: str, answer: str, topic: str) -> dict:`。

「讀寫失敗就直接報錯」的設計是對的,1.x 也確實會把例外包成 `isError: true`。問題在包裝的方式。venv 裡 SDK 的 `mcp\server\fastmcp\tools\base.py:117` 是:

```python
raise ToolError(f"Error executing tool {self.name}: {e}") from e
```

`str(e)` 原封不動送出去。所以檔案被防毒或同步軟體鎖住時,模型會收到類似 `Error executing tool add_card: [Errno 13] Permission denied: '<home>\\work\\tools\\public\\mcp-flashcards\\cards.json'` 的字串,等於把 Windows 使用者名稱和目錄結構都送出去了。如果是 `os.replace` 失敗,`.tmp` 和目標檔兩條路徑會一起送出。另外 1.x 對 tool 失敗完全不寫 server log,stderr 上什麼都看不到。沒有憑證外洩,所以是 Medium。

**修法:** 所有 I/O 都經過 `_load` 和 `_save`,改這兩個地方就夠了:
1. 用 `except OSError:` 接住,先 `logger.exception(...)` 把細節記到 stderr(`logging.getLogger(__name__)`,stdio 下是安全的)。
2. 再 `raise ToolError("Could not read the card file (permission denied or locked by another program). See server logs.")`。

想更完整的話,每個 tool 外層再加 `except ToolError: raise` / `except Exception: logger.exception(...); raise ToolError("Internal error; see server logs")`。這樣 cards.json 是合法 JSON 但結構不對時產生的 `KeyError` 或 `AttributeError` 也會被接住。

## Checked and clean

- **R2:** 沒有 raise `McpError`。
- **R3:** 參數都有型別(`card_id: int`、`correct: bool`),也沒有手寫檢查後 return 字串。
- **R5:** 沒有 low-level handler。
- **R6:** 沒有建 `CallToolResult`,也沒有 `isError`/`is_error` key。
- **R7:** stdio 加 1.x 是最危險的組合,但 server.py 沒有 `print`、`sys.stdout`、`os.write`、輸出到 stdout 的 logging、rich/click 或 subprocess。
- **R9:** 沒有寫死的憑證,`.gitignore` 有排除 `.env`。
- **R10:** `DATA_FILE` 用 `Path(__file__).with_name`,README 只放 placeholder 路徑。
- **R11:** 沒有用 tool 參數組路徑。
- **R13:** 沒有 resource。
- **R15:** 見上面的 pin。

`server.py:146` 的 `return {"ok": False, "message": "No cards to review"}` 不算問題。它是按 topic 篩選抽卡,結果為零筆而且有明說,屬於 R1 明文豁免的情況。唯一小事是 `ok: False` 可能讓模型把「這個主題還沒有卡」講成失敗,這只是措辭問題。

不適用的規則:R8 和 R14 只管 2.x,R12 只管 HTTP。順帶一提,`threading.Lock` 在 1.x 上是多餘但無害的,將來遷到 2.x 時剛好已經擋掉 R14 的問題。

## Could not verify

1. **`server.py:60` `if not DATA_FILE.exists():` 在 Python 3.14.5(venv 用的版本)上的行為。** 我記得 3.13 起 `Path.exists()` 改成呼叫 `os.path.exists()`,而後者遇到任何 OSError(例如 stat 被拒絕存取)都會回 False,不會丟例外。如果真是這樣,這種情況下 `_load()` 會默默回空 store,繞過 docstring 說的「其他 I/O 錯誤一律 raise」,接下來 `add_card` 的 `os.replace` 就可能覆蓋真正的檔案。我需要讀 stdlib 原始碼才能確認,但讀取 Python 安裝目錄的權限被拒,所以沒驗到。這要很特殊的 ACL 才會觸發,機率低。便宜的加固方式是拿掉 `exists()` 預檢,直接 `open`,只 `except FileNotFoundError: return _empty()`。
2. **pin 的下界。** `mcp>=1.2,<2` 允許裝到 1.2 到 1.29,但規則只在 1.30.0 驗證過,R4 的錯誤包裝文字在這些舊版可能不同。你本地 venv 是 1.30.0,沒問題。全新安裝會拿到最新的 1.x,我查不了 PyPI,不確定有沒有比 1.30.0 更新的 1.x。想鎖定在驗證過的版本,可以改成 `mcp>=1.30,<2`。

---

要的話,我可以把第 1 條(壞檔被當成空牌組)的修法草稿寫出來給你看,或者先把「Could not verify」第 1 條的 `Path.exists()` 行為查清楚。你說一聲我再動,檔案我現在都沒碰。
