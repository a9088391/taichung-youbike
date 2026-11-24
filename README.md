# 臺中 YouBike 站點供需儀表板

在本機 Grafana 查看臺中市政府提供的 YouBike 站況。總覽顯示來源涵蓋的站點和行政區、站點地圖、可借車數、可還空位及來源時間。

## 本機啟動

需要 Docker、Docker Compose 和 OpenSSL。在專案根目錄執行：

```sh
./bin/local up -d --build --wait
```

開啟 [本機 Grafana 總覽](http://127.0.0.1:5088/d/taichung-youbike/taichung-youbike)。採集程式在啟動時執行一次，之後約每十分鐘擷取。第一次成功後儀表板會顯示站點；畫面每分鐘更新，也可手動重新整理。

`bin/local` 首次執行會產生本機 `.env` 憑證。保留此檔案及 PostgreSQL volume，以便停止後繼續使用原資料。Grafana 只綁定 `127.0.0.1`，以唯讀 Viewer 開啟。資料庫採集與檢視使用不同角色，資料庫連接埠只在 Compose 網路內使用。若 5088 已被占用，可在啟動時以 `YOUBIKE_GRAFANA_PORT` 指定本機連接埠。

```sh
./bin/local logs --tail 40 collector
./bin/local stop
```

## 來源與更新狀態

資料由[臺中市政府交通局](https://data.gov.tw/dataset/136781)提供，依政府資料開放授權條款第 1 版使用。各站「來源時間」為市府的站點資料時間，「最後成功採集」為本機完成並保存整批資料的時間，畫面皆使用臺灣時間。

如果抓取、資料驗證或儲存失敗，採集程式會記錄錯誤，並在下次排程再嘗試。只要資料庫可連線，就會更新採集狀態；最後一次成功快照仍可查看。資料庫無法讀取時，Grafana 會顯示資料來源錯誤。重抓同一站點與來源時間時，只保留一筆觀測。

## 採集程式測試

本票使用專案固定版本的 Python 容器執行既有15項採集單元測試、前置回歸測試及整合驗證，不需在主機安裝 `psycopg`。隔離目標與完整命令順序見下方「隔離整合驗證」。

## 早晚尖峰排行與單站歷史

從總覽上方「早晚尖峰與單站歷史」連結進入，或開啟[尖峰與歷史儀表板](http://127.0.0.1:5088/d/taichung-youbike-peaks/taichung-youbike)。選擇行政區、站點和右上方日期範圍；選單的 `All` 代表所有選項。站點以站號識別，選單顯示名稱及站號，已從最新快照消失的站點仍可從留存歷史查詢。

早尖峰為臺灣時間週一至週五 `07:00 ≤ 來源時間 < 09:00`，晚尖峰為 `17:00 ≤ 來源時間 < 19:00`。兩個尖峰在所選日期內各自累計。缺車比例為無車有效觀測數除以有效觀測數，缺位比例則以無位觀測分開計算。例如24筆中6筆無車、3筆無位，分別為25%與12.5%。每站、每個尖峰至少24筆才列入排行；23筆仍會出現在比例明細。

有效觀測須營運中，且來源時間不晚於首次採集時間、首次採集時來源年齡不超過30分鐘（正好30分鐘可計入）。重抓同一站號與來源時間只算一筆，資格依首次採集判定。停用、缺報、超時及未來時間不納入比例。缺報沒有觀測列，整批格式無效仍依既有採集失敗流程處理。這些比例描述已採集樣本，不代表完整時段的時間比例。

選擇一個站點即可查看所有時段的單站歷史觀測點與明細。歷史圖只繪製有效觀測點，不連線或推算缺報、停用等時段；明細保留不合格觀測及原因。零筆有效觀測或採集開始前的日期會顯示「無資料」；不補零，也不回填尚未採集的歷史。

### 已有第01版資料庫的升級

新 volume 啟動時會自動建立 `station_history` 檢視。既有 volume 不會重跑初始化；請先在原專案目錄明確套用下列新增檢視，再啟動或更新服務：

```sh
./bin/local exec -T db psql -v ON_ERROR_STOP=1 -U youbike_admin -d youbike < postgres/peak-history.sql
./bin/local up -d --build --wait
```

腳本只以交易建立或更新檢視並授予 `youbike_reader` 的 SELECT 權限，可重複執行，不改動既有觀測、站點總覽或採集狀態。套用失敗會回滾該交易；保留原 volume 和 `.env`，不要以刪除 volume 的方式升級。若只退回第01版程式，原資料與原總覽仍可使用，新增檢視可留存。

### 隔離整合驗證

`tests/integration_peak_history.py` 使用市府格式的本機 HTTP 測資，透過實際 `collector.main --once --source-url`、解析及資料庫寫入後，執行受版本控制的 Grafana SQL。HTTP server 在整合測試的 collector 容器內綁定 loopback，採集程式從同一容器連回，不需主機開 HTTP 連接埠。僅測試時替換採集時鐘以重現30分鐘與早晚尖峰邊界，正式採集程式沒有時鐘參數。

使用獨立 Compose project `taichung-youbike-ticket02-check` 和連接埠5092；Compose project、volume 與網路隔離資料，沿用 repo 根目錄的私有 `.env`。以下順序只啟動 `db grafana`，不啟動週期採集器。`./bin/local config --quiet` 只在缺少時建立 `.env` 並檢查 Compose 設定，不會啟動5088展示。接著在同一終端機設定同一份私有環境給 Compose 及整合容器使用：

```sh
ticket02_project=taichung-youbike-ticket02-check
./bin/local config --quiet
set -a
. ./.env
set +a
export YOUBIKE_GRAFANA_PORT=5092
docker compose --env-file .env -p "$ticket02_project" up -d --wait db grafana
docker compose --env-file .env -p "$ticket02_project" ps
docker compose --env-file .env -p "$ticket02_project" port grafana 3000
docker volume ls --filter "label=com.docker.compose.project=$ticket02_project"
```

確認 `ps` 顯示專案 `taichung-youbike-ticket02-check` 的 `db`、`grafana` 服務，`volume ls` 顯示同專案標籤的資料庫 volume，且 `port` 顯示 Grafana 綁定 `127.0.0.1:5092`。確認目標後，在同一終端機為該隔離資料庫設定標記，再建置採集容器並執行測試：

```sh
ticket02_project=taichung-youbike-ticket02-check
set -a
. ./.env
set +a
export YOUBIKE_GRAFANA_PORT=5092
docker compose --env-file .env -p "$ticket02_project" exec -T db \
  psql -v ON_ERROR_STOP=1 -U youbike_admin -d youbike \
  -c "COMMENT ON DATABASE youbike IS 'ticket02-check disposable verification';"
docker compose --env-file .env -p "$ticket02_project" build collector
docker compose --env-file .env -p "$ticket02_project" run --rm --no-deps -T \
  -v "$PWD/tests:/app/tests:ro" -v "$PWD/grafana:/app/grafana:ro" \
  collector python -B -m unittest discover -s tests -v
docker compose --env-file .env -p "$ticket02_project" run --rm --no-deps -T \
  -e TICKET02_DISPOSABLE=ticket02-check -e YOUBIKE_READER_PASSWORD \
  -v "$PWD/tests:/app/tests:ro" -v "$PWD/grafana:/app/grafana:ro" \
  collector python -B tests/integration_peak_history.py
```

識別標記只設定在這個隔離資料庫；不可對一般展示資料庫執行。測試命令在容器內執行，不會輸出 `.env` 內容。

整合測試在 HTTP fixture 送出前核對資料庫標記、測資站號與 `youbike_collector`／`youbike_reader` 身分；以唯讀查詢檢查採集表、`current_stations`、`station_history` 及兩張 dashboard 的實際查詢。Stat reducer 檢查使用 reader 查詢回傳的欄位型別與欄名，不能以這些 SQL 檢查代替 Grafana 畫面驗收。預期保留442筆觀測，可在同一隔離資料庫重跑以驗證去重，不需清除資料。測試涵蓋30分鐘內／等於／超過、未來來源時間、停用、缺報、無效批次復原、早晚與週末邊界、23／24筆、比例、篩選、點狀歷史與單站明細。

### Grafana 畫面驗收與證據

使用已授權的本機瀏覽器工具操作5092上的實際 Grafana；僅在完整畫面證據可讀時記錄通過。遇到瀏覽器限制時保留阻擋並回報，使用者恢復控制後再繼續。每次選擇行政區、站點或日期後，等待受影響面板完成載入並呈現新選擇的結果，再保存證據。每份證據記錄程式版本或未提交來源檔雜湊、Compose project／目標 URL、Grafana 角色、所選行政區與站號、精確日期範圍，以及完整可獨立閱讀的 DOM 或 AX 狀態；若只保存差分，須同時保存其完整基準。主張圖表外觀或點線行為時一併保存截圖。

將完整原始狀態與截圖保存在本票既有的 `../.scratch/taichung-youbike/review/02/` 驗收目錄，保留必要 metadata；對話與摘要只引用檔名和關鍵觀察，不重複貼出整份 DOM、AX 或報告。驗收至少涵蓋：

第一次可用的單站歷史圖驗證，先完成下表站點 A 長空檔與 CLOCK 營運中／停用／營運中案例，等待結果更新並保存完整狀態與截圖，再進行其餘驗收案例。

| 操作 | 畫面結果 |
| --- | --- |
| 西屯區站點 B，2026-11-16–2026-11-18 | 早、晚各23筆，不列排行；比例明細各23筆、歷史46筆。 |
| 北區站點 C，2026-11-16–2026-11-18 | 早、晚排行各24筆、歷史48筆。 |
| 北區站點 C，2026-11-16–2026-11-17 | 早、晚各12筆、不列排行；明細各12筆、歷史24筆。 |
| 西屯區站點 A，涵蓋兩天 | 早尖峰24筆、缺車25%／缺位12.5%；晚尖峰24筆、缺車50%／缺位25%；歷史48個有效點，08:50至17:00長空檔沒有連線或補值。 |
| 站點 CLOCK，2026-11-22 09:55–10:25 | 歷史圖只顯示2個有效點；明細保留3筆及中間停用原因。 |
| 零筆及採集前日期（2020-01-01–2020-01-02） | 顯示「無資料」。 |
| 停用站 T02-INACTIVE，2026-11-16–2026-11-18 | 全部48筆不合格，歷史圖無點，狀態提示不合格；明細保留原因。 |
| 站點選擇 All | 未選單一站點時顯示先選站提示。 |
| 總覽與尖峰歷史 | 實際操作連結來回切換，確認兩個方向都開啟正確儀表板。 |

完整狀態需包含當次選擇及完成更新後的面板內容。保留原始檔供 Spec／Review 獨立讀取；只在驗收記錄中摘要各項結果。
