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

```sh
python3 -B -m unittest discover -s tests -v
```

測試使用本機 HTTP 伺服器。需要演練整條採集流程時，請以獨立 Compose project 和測試連接埠啟動資料庫及 Grafana，再以採集程式的 `--once --source-url` 接收受控 HTTP 資料。
