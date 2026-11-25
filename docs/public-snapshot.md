# 固定展示快照操作

此文件區分本地預覽與公開發布。2026-11-24的v1候選曾獲一次發布核准並已發布；2026-11-25的v2候選依核准SHA256單次發布，v1連結仍保留。網站科技藍改版與七項作品截圖已發布；本次v2入口更新以網站提交 `b13277a4d69367eeaff04d893aab06847d073ff9` 發布，Main已依直接授權完成該網站repo的commit／push及公開入口驗收。以上不授權覆寫v1公開URL、撤銷快照、其他跨repo寫入／發布或YouBike repo的Git操作。`public_snapshot.py` 不提供上傳功能。隔離環境、測試與瀏覽器原始證據程序以 [README](../README.md#第04張隔離準備與驗證) 為唯一來源。

## 候選內容與輸出檢查

`prepare` 從既有reader讀取成功快照，不修改DB；狀態、擷取時間與全市站點在同一個 `REPEATABLE READ READ ONLY` 交易取得。公開欄位只有站號、站名、行政區、座標、總車位、可借車數、可還空位、各站來源時間及營運狀態。站名限制公開文字字元，站號限定數字，29區須完整，空資料或不一致一律拒絕。v1與v2各使用明確版本的固定原生Stat／Geomap／Table／Text配置，不使用原dashboard export，也不複製SQL、datasource、連線資訊、變數、月報／尖峰連結或refresh。`check` 僅接受JSON整數 `version` 1或2，且拒絕布林值、浮點數、字串及其他版本；以對應模板重建完整輸出後精確比較。

本次已發布v2候選以實際檔案執行下列檢查，並將核准與上傳綁定同一個SHA256。未來候選須對新輸出的實際檔案重做檢查及取得該候選的直接核准：

```sh
python3 -B public_snapshot.py check ../.scratch/taichung-youbike/review/04/restyle-20261125/runtime/public-snapshot-v2-r2.json
shasum -a 256 ../.scratch/taichung-youbike/review/04/restyle-20261125/runtime/public-snapshot-v2-r2.json
```

工具從map frame的資料與固定時間重建全部面板，再與完整輸入精確比較。因此額外設定、隱藏frame metadata、查詢、資料源、不一致KPI／區表／明細、任意連結或刷新都會失敗；JSON重複key也拒絕。仍須由獨立接受者核對實際候選的每個公開欄位、時間、資料來源及批准發布的雜湊；工具不會判斷未來新增的業務機密是否可公開。

### v2候選與本機驗證紀錄

v2沿用固定全市資料範圍，改用版本2的Grafana原生面板呈現。以Grafana 13.3.1在5095隔離環境檢查：375×812手機畫面首次載入可見提示標籤且無內層裁切；已操作地圖tooltip／縮放，並翻至區表末頁（石岡3站、和平2站）及站點表末頁（第1849–1851列，共1,851站）。資料時間為擷取2026-11-24 19:36:02、快照建立2026-11-25 01:21:05（臺灣時間）。

本機候選 `public-snapshot-v2-r2.json` 的SHA256為 `11765db86444494ffdf251926e03bd25c35bfcdd06b0efbf0a905706de7dfc2f`；v2來源版本的摘要以驗收目錄所存紀錄為準。匿名本機快照key只供5095預覽，不是公開URL。重新採集後已確認同一5095快照API回應SHA256為 `a115dff97443207158b829ec3551869702664481b43343c49125d6b19754a800`，逐位元不變；重載後畫面仍顯示同樣站數與兩個時間。原始AX、DOM、截圖與固定性log保存在本票驗收目錄。本機範圍已通過四lane獨立Review與Main接受，見 `restyle-20261125/grafana-local-acceptance.md`。

v2已發布至官方快照服務：[匿名公開快照](https://snapshots.raintank.io/dashboard/snapshot/c99414bd980a67f72ad3f0a159766685)。發布使用候選 `public-snapshot-v2-r2.json`（SHA256 `11765db86444494ffdf251926e03bd25c35bfcdd06b0efbf0a905706de7dfc2f`），官方服務版本 `13.4.0-44540513276`，單次POST回覆HTTP 200。匿名API回應413,980 bytes、SHA256 `7a45a53f549b378417357f542b63fb8a26c177da3abf42cb5689e82a9c2113bd`；所有核准dashboard欄位與候選相同，服務只加入 `snapshot.originalUrl=""`。API回傳 `meta_created=2026-11-25T05:21:06Z`、`meta_expires=2076-11-12T05:21:06Z`，均為UTC；未設到期（Never）不代表第三方服務永久可用。

匿名Chrome已檢查1440×900畫面上的四張Stat、全市地圖與tooltip、20／10／50km縮放、區表末頁（石岡3站、和平2站）、站點表末頁（第1849–1851列，共1,851站）、來源與授權連結；375×812手機畫面上的提示badge完整可見。tooltip抽查站號500626001，顯示9可借、11可還、營運中，來源時間2026-11-24 19:35:04。重新採集後reader逐欄相符且最後成功時間前進；同一公開key的匿名API回應bytes／SHA256與原日期不變，公開URL重新載入仍顯示相同日期。瀏覽器console仍有 `Error fetching Prometheus write target` 與 `Object` 記錄，根因未確認，不宣稱沒有console錯誤。原始公開證據見 `restyle-20261125/publication-v2/public-acceptance-before-website.json` 與同目錄原始紀錄。

## 只建立本地原生 Snapshot

本地Grafana13.3.1預設停用管理者登入及Basic API，匿名Viewer不能建立快照。僅本票驗證使用下列override，保留既有admin密碼與角色、匿名Viewer、loopback綁定和其他設定，不修改專案的 `compose.yaml`：

```sh
mkdir -p ../.scratch/taichung-youbike/review/04
cat > ../.scratch/taichung-youbike/review/04/compose.snapshot-check.yaml <<'YAML'
services:
  grafana:
    environment:
      GF_AUTH_BASIC_ENABLED: "true"
YAML
set -a
. ./.env
set +a
export YOUBIKE_GRAFANA_PORT=5095
docker compose --env-file .env -p taichung-youbike-ticket04-check \
  -f compose.yaml -f ../.scratch/taichung-youbike/review/04/compose.snapshot-check.yaml \
  up -d --no-deps --wait grafana
docker inspect taichung-youbike-ticket04-check-grafana-1 \
  --format '{{json .HostConfig.PortBindings}} {{index .Config.Labels "com.docker.compose.project"}}'
docker compose --env-file .env -p taichung-youbike-ticket04-check exec -T grafana \
  sh -c 'printf "%s %s %s %s\n" "$GF_AUTH_BASIC_ENABLED" "$GF_AUTH_ANONYMOUS_ENABLED" "$GF_AUTH_ANONYMOUS_ORG_ROLE" "$GF_AUTH_DISABLE_LOGIN_FORM"'
```

核對project為本票、只綁 `127.0.0.1:5095`，後四項依序 `true true Viewer true`；不輸出 `.env` 或完整container環境。確認候選通過後，以下程式只向5095建立 `external=false` 本地快照。Grafana一般模式需驗證來源dashboard存在，故只在本地請求暫附既有 `uid=taichung-youbike`；原候選檔完全不變。服務另加入的 `dashboard.snapshot` 原始連結等metadata只用於本地預覽，不得複製進公開候選。

```sh
python3 -B - <<'PY'
import base64
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
import public_snapshot

candidate = Path('../.scratch/taichung-youbike/review/04/restyle-20261125/runtime/public-snapshot-v2-r2.json')
payload = json.loads(candidate.read_bytes(), object_pairs_hook=public_snapshot.unique_object)
public_snapshot.check_payload(payload)
assert payload['external'] is False
payload['dashboard']['uid'] = 'taichung-youbike'  # 僅本地權限查核使用
credential = base64.b64encode(('admin:' + os.environ['YOUBIKE_GRAFANA_ADMIN_PASSWORD']).encode()).decode()
request = Request('http://127.0.0.1:5095/api/snapshots',
    data=json.dumps(payload).encode(), method='POST',
    headers={'Content-Type': 'application/json', 'Authorization': 'Basic ' + credential})
# 回應包含deleteKey/deleteUrl，禁止放進Git、公開檔或Review輸入。
# 發送前先排他建立私有回應檔，避免已有檔案時仍送出建立請求。
with os.fdopen(os.open('/tmp/youbike04-local-snapshot-response.json',
        os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as output:
    with urlopen(request, timeout=30) as response:
        result = json.load(response)
    json.dump(result, output)
with urlopen('http://127.0.0.1:5095/api/snapshots/' + result['key'], timeout=30) as response:
    saved = json.load(response)
assert all(saved['dashboard'][key] == value for key, value in payload['dashboard'].items())
print('http://127.0.0.1:5095/dashboard/snapshot/' + result['key'])
PY
```

建立成功後只公開列印本地檢視key的URL，撤銷秘密留在權限0600的非repo檔。若請求超時或結果未知，先以管理者唯讀 `GET /api/dashboard/snapshots` 查詢及匿名讀回確認，不能直接重送建立。先前回應檔存在時應先保留它，並為新的一次建立選擇另一個私有檔名；不得覆蓋或刪掉既有撤銷秘密。

本地Grafana資料在容器內；重建容器可能失去快照與其URL，保留候選JSON可重建。驗證完成後如需恢復隔離Grafana預設設定，可用原Compose明確recreate僅本票grafana服務；這會使本地預覽可能失效，須先結束畫面／固定性驗收並保留候選、證據，不能將此動作擴及其他project。不得刪PostgreSQL volume。

## 一次公開發布紀錄與後續授權

使用者核准的唯一候選SHA256為 `0785e08d980a37e4742a46b5c6375c0f3725e2d28777ff90392bc6793070920f`，含1,851站／29區，於2026-11-24 16:46:16建立，站點資料擷取時間為16:42:45（臺灣時間），發布至官方目的地 `https://snapshots.raintank.io`。Grafana官方服務版本為 `13.4.0-43210257101.patch1`。發布HTTP狀態200；[實際公開快照](https://snapshots.raintank.io/dashboard/snapshot/a871792d80d21c2b0eea09af3313b069) 可匿名讀取，公開API回應包含的dashboard欄位與核准候選相同。

本次請求 `expires=0`（Never），服務回傳的 `meta_created` 為 `2026-11-24T11:32:25Z`、`meta_expires` 為 `2076-11-11T11:32:25Z`；保留服務原始UTC值，不將其視為快照內的臺灣時間欄位。不設到期不保證第三方服務永久可用。發布期間的瀏覽器console記錄一筆 `Error fetching Prometheus write target` 及兩筆 `Object` 錯誤。根因未確認；已驗證的KPI、地圖tooltip、縮放、站點明細、行政區表格及重載後固定性正常，錯誤原始記錄保存在本票驗收資料。

README列出的三項v1公開驗收保留為歷史結果。2026-11-25重新檢查v1時，匿名API回應逐位元相同，但瀏覽器只有Grafana外殼、沒有面板；目前v1畫面可用性未通過，原因待查。v2已通過匿名公開瀏覽及互動、同一公開URL固定性、個人網站入口抵達三項驗收；網站入口已發布並實測另開新分頁抵達同一v2快照。網站科技藍改版曾加入YouBike v2資料的截圖，該圖不是公開服務截圖。

網站已發布證據分成兩次Pages部署記錄：`website-finish/pages-deployment.json` 記錄run `45522926874` 成功部署提交 `9625dea93b3023f779d21dd606c809db22925068`；同目錄的 `all-seven-image-results.json` 與 `images-final-390-*` AX／DOM／JPG 保留七張作品圖及390px畫面證據。後續 `website-interaction/pages-deployment.json` 記錄run `45536548919` 成功部署提交 `3d94795d671f266c3b96c86926ed08f311680ca2`，加入作品卡互斥展開與新分頁行為；本次沒有重新執行圖片或RWD檢查，因CSS、圖片及其相關標記未變，沿用前述有效驗收。以上是先前兩次網站部署證據。本次v2入口另以提交 `b13277a4d69367eeaff04d893aab06847d073ff9`、Pages run `45555845226` 成功部署；Main從正式作品區實際另開新分頁抵達新版快照，核對未登入狀態、標題、1,851站／29區、兩個日期及來源，原作品頁展開狀態保留。375px手機卡片的新日期／caption正常換行、圖片載入且無水平溢出；本次只重驗受影響卡片，未冒稱重跑所有圖片或所有RWD尺寸。原始證據為 `restyle-20261125/publication-v2/website-public-*`，部署紀錄為同目錄 `pages-deployment.json`。若要發布新的快照候選，須重新檢查實際輸出、範圍、官方服務及候選雜湊，並先取得該候選的直接核准；既有v1授權不可沿用，亦不得覆寫v1 URL。

發布操作依當時官方API契約執行單次請求，重新執行 `check` 並比對核准雜湊。保留候選原檔，只使用候選的 `dashboard`、`name`、`expires=0`；不使用本地API讀回的 `uid`、`snapshot.originalUrl` 或其他metadata。Grafana13.3.1的external sender送至公開接收端的envelope為 `dashboard`、`name`、`expires`、`key`、`deleteKey`；key與deleteKey須使用獨立的強隨機值，私下保存deleteKey。`external=true` 是一般Grafana轉送至外部服務的控制，不應將本地建立程序改為true當作探測；若走一般Grafana轉送，官方契約另要求key與deleteKey。本票的發布HTTP狀態為200，匿名API及Chrome畫面已確認公開讀取；若未來更換目的地或改用另一種Grafana轉送方式，須重新核對當時契約。

服務拒絕或結果不明時，先以先前保存的公開檢視key匿名讀回，不重送建立；若要撤銷快照，須另行取得授權並使用保存的deleteKey／deleteUrl。不得把刪除連結當成一般檢視連結測試，因為GET本身可能觸發刪除。敏感回應以0600存放於repo外，不放README、截圖、網頁、Review或日誌。撤銷無法收回他人副本；官方API提到快取移除可能延遲約一小時。程式碼退版不會刪除已公開快照，也不會復原網站變更。

## 版本契約來源

- [Grafana Snapshot說明](https://grafana.com/docs/grafana/latest/visualizations/dashboards/share-dashboards-panels/#share-a-snapshot)：Snapshot保留可見資料，原生面板需實測，custom panels不支援。
- [Snapshot HTTP API](https://grafana.com/docs/grafana/latest/developer-resources/api-reference/http-api/api-legacy/snapshot/)：建立需要含資料的完整dashboard、到期與key/deleteKey契約。
- [v13.3.1 PanelModel](https://github.com/grafana/grafana/blob/v13.3.1/public/app/features/dashboard/state/PanelModel.ts)：`snapshotData` 為 `DataFrameDTO[]`。
- [v13.3.1 Snapshot service](https://github.com/grafana/grafana/blob/v13.3.1/pkg/services/dashboardsnapshots/service.go)：一般模式dashboard存在查核、public mode與external sender的實際請求差異。
