() => {
  const clean = value => (value || "").replace(/\s+/g, " ").trim();
  const read = selector => clean(document.querySelector(selector)?.textContent);
  const items = selector => [...document.querySelectorAll(selector)]
    .map(node => clean(node.textContent)).filter(Boolean);
  const main = document.querySelector("#landingImage, #imgBlkFront");
  const picture = main?.getAttribute("data-old-hires") || main?.currentSrc || "";
  const details = {};
  for (const row of document.querySelectorAll(
    "#productOverview_feature_div tr, #productDetails_techSpec_section_1 tr, #productDetails_detailBullets_sections1 tr"
  )) {
    const cells = row.querySelectorAll("th, td");
    if (cells.length >= 2) {
      const key = clean(cells[0].textContent).toLowerCase();
      const value = clean(cells[1].textContent);
      if (key && value && !Object.hasOwn(details, key)) details[key] = value;
    }
  }
  return {
    origin: location.origin,
    pathname: location.pathname,
    selected_asin: document.querySelector("#ASIN")?.value || "",
    title: read("#productTitle"),
    brand: read("#bylineInfo").replace(/^(Brand:\s*|Visit the\s*)/i, "").replace(/\s+Store$/i, ""),
    platform_category: items("#wayfinding-breadcrumbs_feature_div li a").join(" > "),
    bullet_points: items("#feature-bullets li .a-list-item").slice(0, 25),
    long_description: read("#productDescription") || read("#aplus"),
    materials: details.material ? [details.material] : [],
    model_number: details["item model number"] || "",
    manufacturer: details.manufacturer || "",
    color: details.color || details.colour || "",
    dimensions: details["product dimensions"] || details["item dimensions l x w x h"] || "",
    main_image: picture ? new URL(picture, location.href).href : "",
    challenge: Boolean(document.querySelector(
      "#captchacharacters, form[action*='validateCaptcha'], #ap_password"
    ))
  };
}
