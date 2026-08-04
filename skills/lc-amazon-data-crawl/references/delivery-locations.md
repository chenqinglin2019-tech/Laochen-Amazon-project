# Amazon Delivery Locations

`config/amazon_delivery_locations.json` is the shared delivery mapping for all
crawler modes. Postal codes are JSON strings so leading zeroes, spaces, and
hyphens are preserved.

The fixed mapping is:

- `amazon.com`: New York — `10001`
- `amazon.ca`: Ottawa — `K1P 1J1`
- `amazon.com.mx`: Mexico City — `06000`
- `amazon.co.uk`: London — `E16 1ZE`
- `amazon.de`: Berlin — `10178`
- `amazon.fr`: Paris — `75004`
- `amazon.it`: Rome — `00186`
- `amazon.es`: Madrid — `28014`
- `amazon.co.jp`: Tokyo — `100-0001`
- `amazon.com.au`: Canberra — `2600`
- `amazon.in`: New Delhi — `110001`
- `amazon.nl`: Amsterdam — `1011 PN`
- `amazon.se`: Stockholm — `111 52`
- `amazon.pl`: Warsaw — `00-950`
- `amazon.ae`: Abu Dhabi — `00000` compatibility placeholder
- `amazon.sa`: Riyadh — `12211`
- `amazon.sg`: Singapore — `179434`
- `amazon.com.br`: Brasilia — `70040-010`
- `amazon.co.za`: Pretoria — `0002`

## File Shape

```json
{
  "locations": {
    "amazon.com": {
      "city": "New York",
      "postal_code": "10001",
      "strategy": "postal"
    },
    "amazon.ae": {
      "city": "Abu Dhabi",
      "postal_code": "00000",
      "strategy": "postal_then_city"
    }
  }
}
```

Normal markets use `strategy: "postal"`: after submitting the address, the
runner must confirm the normalized postal code before extraction. Keep the
configured value unchanged in the mapping even when the Amazon form requires a
compact retry without spaces or hyphens.

UAE uses `strategy: "postal_then_city"`. The runner first tries `00000` only as
a form-compatibility placeholder. If the site has no postal-code input or
rejects the value, it selects Abu Dhabi and confirms the city instead. Do not
describe `00000` as an official UAE postal code; Emirates Post documents UAE
addresses without a postal-code field in its addressing guidance:
<https://www.emiratespost.ae/faq>.

If automatic selection cannot be confirmed, the user may complete the current
visible Amazon prompt during `manual_pause_timeout`. Otherwise the crawler must
raise `delivery_location_unconfirmed` and stop before writing page records.

The delivery setting is stored by Amazon in the dedicated browser Profile and
can affect prices, availability, shipping promises, and result ordering. Cache
confirmation only by current driver plus exact domain; never reuse it across a
browser restart or marketplace change.
