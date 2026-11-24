# 專案指引

- 執行整合或 Grafana 驗收前，依 [README.md](README.md#隔離整合驗證) 與 [README.md](README.md#grafana-畫面驗收與證據) 操作；README 是瀏覽器證據程序的唯一來源。
- Grafana 文字 Stat 面板可參考 `station-overview.json` 第3、4面板的 `reduceOptions.fields` 與 `values` 明確設定。`tests/integration_peak_history.py` 會用實際 reader 查詢 metadata 核對兩張儀表板的所有文字 Stat；數字 Stat 保留既有 reducer。此檢查不代表 Grafana 畫面驗收通過。
- 保留單站歷史圖的點狀顯示。整合預檢會拒絕連線樣式；保留站點 A 長空檔與週日 CLOCK 營運中／停用／營運中的測資，並在 Grafana 確認實際呈現。
- 瀏覽器驗收時，若支援 `emit: false`，先檢視已授權的目標清單；完整快照依 README 證據程序保存，對話只摘要相關瀏覽器與5092目標。依附帶的 RTK 指引控制 shell 輸出、重用現有讀取，截斷後只補讀缺少範圍。

@/Users/ksy/.codex/RTK.md
