# Official verification sources

## United States

- Patents and designs (visible Chrome CDP Basic Search): https://ppubs.uspto.gov/basic/
- Patent assignments: https://assignmentcenter.uspto.gov/
- Trademark search: https://tmsearch.uspto.gov/
- Trademark status/documents: https://tsdr.uspto.gov/
- Copyright records: https://publicrecords.copyright.gov/

## European Union

- WIPO PATENTSCOPE operator-performed recall: https://patentscope.wipo.int/
- Espacenet manual website only; do not automate: https://worldwide.espacenet.com/
- EPO OPS automated patent retrieval / non-US primary discovery: https://ops.epo.org/
- EUIPO Trademark Search API: https://dev.euipo.europa.eu/product/trademark-search_100
- EUIPO Design Search API: https://dev.euipo.europa.eu/product/design-search_100
- EUIPO Sandbox portal: https://dev-sandbox.euipo.europa.eu/
- EUIPO Sandbox authentication: https://auth-sandbox.euipo.europa.eu/oidc/accessToken
- EUIPO Sandbox API base: https://api-sandbox.euipo.europa.eu/
- EUIPO public search: https://euipo.europa.eu/eSearch/

## Other common markets

- United Kingdom: https://www.gov.uk/search-for-patent
- Canada: https://ised-isde.canada.ca/site/canadian-intellectual-property-office/en/search-intellectual-property-databases
- Mexico: https://www.gob.mx/impi
- Japan: https://www.j-platpat.inpit.go.jp/
- Australia: https://search.ipaustralia.gov.au/

Use the official candidate jurisdiction whenever possible. Record URL, query, checked time, screenshot, and status. Aggregator zero results are not official clearance.

For US patents, first capture operator-confirmed low-frequency PATENTSCOPE results, execute planned EPO OPS queries, and capture `ppubs.uspto.gov/basic/` through visible Chrome CDP. Use Patent Public Search again for candidate-level official verification after the displayed record identifier and required page fields match the candidate. For US trademarks, use the rendered `tsdr.uspto.gov` case page through visible Chrome CDP. Pass each capture through the relevant validated recorder.
