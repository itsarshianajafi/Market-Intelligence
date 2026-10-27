# Official source investigation

Checked from the project cloud workspace on 27 October 2026. These observations
are about this workspace at this time, not proof a source is unavailable to everyone.
No transaction records were retrieved during these checks.

| Official candidate | Observed result | Suitability |
| --- | --- | --- |
| [DLD Real Estate Data](https://dubailand.gov.ae/en/open-data/real-estate-data/) | Page and its public JavaScript loaded successfully with a normal User-Agent. Transactions tab offers Download as CSV. Current page configuration enables CAPTCHA, and transaction searches check it before querying. | Official transaction-level export candidate for manual retrieval. Page explicitly directs previous-year requests to Data Dubai. No CAPTCHA bypass attempted; unattended collection has not been validated. |
| [DLD Real Estate Transactions service](https://dubailand.gov.ae/en/eservices/real-estate-transaction/) | Page loaded successfully; the client displays transaction counts and values by area and period. | Dashboard access does not establish availability of individual transaction records. Not substituted for the transaction CSV. |
| [DLD API Gateway](https://dubailand.gov.ae/en/eservices/api-gateway/#/) | Page loaded successfully. Lists named business integrations with subscriptions/prerequisites, including Ejari, Mollak, Trakheesi and others. | No public historical transaction-record endpoint identified on the inspected page. Do not assume that signing up provides access to the dataset. |
| [Data Dubai transaction catalogue](https://data.dubai/en/l/470061) | HTTP 200 with a small HTML Request Rejected page, including on retry. | Not a successful catalogue or data response. |
| [Dubai Pulse legacy catalogue API](https://www.dubaipulse.gov.ae/api/3/action/package_show?id=dld-transactions) | HTTP 503 Service Unavailable. | Could not discover a resource through this legacy route. |
| [Dubai Statistics Center housing/building page](https://www.dsc.gov.ae/en-us/Themes/Pages/Housing-and-Building.aspx) | Proxy tunnel HTTP 403. | Content and transaction-level coverage could not be inspected. |
| [Dubai Statistics Center open data candidate](https://www.dsc.gov.ae/en-us/Pages/OpenData.aspx) | Proxy tunnel HTTP 403. | Candidate path not independently verified; no data retrieved. |
| [UAE official open data guidance](https://u.ae/en/about-the-uae/digital-uae/data/open-data) | Proxy tunnel HTTP 403. | Discovery page, not a verified transaction dataset. |
| [Bayanat](https://bayanat.ae/) | Proxy tunnel HTTP 403. | Current availability and relevant coverage unverified. |
| [Federal statistics open data candidate](https://opendata.fcsc.gov.ae/) | Proxy tunnel HTTP 403. | Relevant coverage unverified. |
| [Federal statistics centre](https://fcsc.gov.ae/en-us/Pages/Statistics/Statistics-by-Subject.aspx) | Proxy tunnel HTTP 403. | Relevant coverage unverified; statistical summaries would not replace transaction records. |

The separately tested legacy Dubai Pulse data API
`https://api.dubaipulse.gov.ae/open/dld/dld_transactions-open-api` returned HTTP
401 with `Unauthorized application request`. Its current authentication contract
and whether dataset subscriptions remain available have not been verified.

## Consequences for this implementation

- The real official source remains DLD, through Data Dubai or DLD's own export.
- No accessible, unattended historical transaction download was established.
- The CLI supports manual English Dubai Pulse/DLD-schema CSVs, ZIP archives,
  multiple export parts, or an explicitly supplied official direct CSV URL. It does
  not automatically discover the portal's
  exports, solve CAPTCHA, or implement an authenticated API.
- DLD's own export uses a different presentation schema: its public UI references
  fields such as TRANSACTION_NUMBER, INSTANCE_DATE, TRANS_VALUE and English
  labels. Its exported CSV header/data types have not been retrieved or validated.
  The importer now maps these published native keys and the corresponding English
  display headers. Tests verify these mappings on artificial records; actual
  export compatibility remains unverified.
- No private listings, fabricated transactions, browser session tokens, or
  dashboard aggregates were used to make the pipeline appear complete.
- Source discovery and real-export validation remain outstanding. A documented
  authorized machine interface or accessible official export is the prerequisite
  for finishing unattended collection; more unverified source URLs do not fix it.
