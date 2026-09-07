import { URL } from "node:url";

// Capability is deliberately scoped to a route, never inferred from an official
// hostname or a successful login. Existing US executors may be acceptance-tested,
// but fixtures and a config flag are not evidence of a live accepted route.
export function getAutomationCapability({ provider, jurisdiction = "", rightType = "", operation = "" }) {
  const route = {
    provider: String(provider || ""), jurisdiction: String(jurisdiction || "").toUpperCase(),
    right_type: String(rightType || ""), operation: String(operation || ""),
  };
  const prohibited = /wipo|patentscope/i.test(route.provider)
    || ["espacenet_browser", "epo_register_browser", "euipo_esearch_browser", "tmview_browser", "designview_browser"].includes(route.provider);
  const contractError = route.provider === "uspto_patent_browser" && route.jurisdiction === "US"
    && ["patent", "design"].includes(route.right_type)
    && !["candidate_verification", `${route.right_type}_recall`].includes(route.operation);
  const existingExecutor = route.jurisdiction === "US" && (
    route.provider === "uspto_patent_browser"
      && ["patent", "design"].includes(route.right_type)
      && (route.operation === "candidate_verification"
        || route.right_type === "patent" && route.operation === "patent_recall"
        || route.right_type === "design" && route.operation === "design_recall")
    || route.provider === "uspto_tmsearch_browser"
      && ["trademark_word", "trademark_figurative"].includes(route.right_type)
      && route.operation === "trademark_recall"
    || route.provider === "uspto_tsdr"
      && ["trademark_word", "trademark_figurative"].includes(route.right_type)
      && route.operation === "candidate_verification"
  );
  return Object.freeze({
    ...route,
    status: prohibited ? "unavailable" : "unvalidated",
    error_code: contractError ? "INTERNAL_ROUTE_CONTRACT_ERROR" : prohibited ? "AUTOMATION_PROHIBITED" : "AUTOMATION_NOT_VALIDATED",
    ...(contractError ? { failure_kind: "internal_contract", submission_state: "not_submitted" } : {}),
    executor_available: Boolean(existingExecutor),
    acceptance_scope: "single_planned_query",
    allowed_user_actions: ["login", "captcha", "mfa", "consent", "qr"],
    business_actions_by: "agent",
    detail: contractError ? `Invalid route: ${route.right_type} requires ${route.right_type}_recall or candidate_verification; no website query was submitted.` : prohibited
      ? "This source does not permit the automated browser query. Manual business-query fallback is disabled."
      : existingExecutor
        ? "An automatic executor exists; a live, plan-bound acceptance run is required before claiming this route is automatic."
        : "No accepted automatic query-and-capture adapter exists for this route. Manual business-query fallback is disabled.",
  });
}

const BASE_METADATA = Object.freeze({
  interaction_mode: "cdp_assisted",
  capture_transport: "cdp",
  user_triggered_only: true,
  bulk_automation: false,
  max_records_per_command: 1,
  terms_checked_at: "2026-09-04",
});

const GLOBAL_ADAPTERS = Object.freeze({
  jplatpat_browser: {
    ...BASE_METADATA,
    authority: "Japan Patent Office / INPIT",
    jurisdictions: ["JP"],
    right_types: ["patent", "utility_model", "design", "trademark_word", "trademark_figurative"],
    operations: ["patent_recall", "utility_model_recall", "trademark_recall", "design_recall", "candidate_verification"],
    search_url: "https://www.j-platpat.inpit.go.jp/",
    terms_url: "https://www.inpit.go.jp/j-platpat_info/guide/j-platpat_notice.html",
    terms_allowed_hosts: ["www.inpit.go.jp"],
    browser_allowed_hosts: ["www.j-platpat.inpit.go.jp", "j-platpat.inpit.go.jp"],
    compliance_note: "Do not perform robot access, periodic collection, pagination loops, or bulk downloads.",
  },
  tmview_browser: {
    ...BASE_METADATA,
    authority: "European Union Intellectual Property Network (TMview)",
    jurisdictions: [
      "EU", "AT", "BE", "BG", "HR", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR",
      "GR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE",
      "SI", "SK", "GB",
    ],
    right_types: ["trademark_word", "trademark_figurative"],
    operations: ["trademark_recall"],
    search_url: "https://www.tmdn.org/tmview/",
    terms_url: "https://www.euipo.europa.eu/info/legal-notices",
    terms_allowed_hosts: ["www.euipo.europa.eu"],
    browser_allowed_hosts: ["www.tmdn.org", "tmdn.org"],
    compliance_note: "Discovery only; verify every material candidate in the competent official register.",
  },
  designview_browser: {
    ...BASE_METADATA,
    authority: "European Union Intellectual Property Network (DesignView)",
    jurisdictions: [
      "EU", "AT", "BE", "BG", "HR", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR",
      "GR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE",
      "SI", "SK", "GB",
    ],
    right_types: ["design"],
    operations: ["design_recall"],
    search_url: "https://www.tmdn.org/tmdsview-web/",
    terms_url: "https://www.euipo.europa.eu/info/legal-notices",
    terms_allowed_hosts: ["www.euipo.europa.eu"],
    browser_allowed_hosts: ["www.tmdn.org", "tmdn.org"],
    compliance_note: "Discovery only; verify every material candidate in the competent official register.",
  },
  epo_register_browser: {
    ...BASE_METADATA,
    authority: "European Patent Office",
    jurisdictions: ["EP", "EU", "DE", "FR", "IT", "ES", "GB", "NL", "BE", "SE", "PL"],
    right_types: ["patent"],
    operations: ["patent_recall", "candidate_verification"],
    search_url: "https://register.epo.org/regviewer",
    terms_url: "https://www.epo.org/en/terms-of-use/terms-and-conditions-use-website-european-patent-office",
    terms_allowed_hosts: ["www.epo.org", "epo.org"],
    browser_allowed_hosts: ["register.epo.org"],
    compliance_note: "Use the Federated Register link for national post-grant status and confirm in the national register.",
  },
  euipo_esearch_browser: {
    ...BASE_METADATA,
    authority: "European Union Intellectual Property Office (EUIPO)",
    jurisdictions: ["EU"],
    right_types: ["trademark_figurative"],
    operations: ["trademark_recall"],
    search_url: "https://euipo.europa.eu/eSearch/",
    terms_url: "https://www.euipo.europa.eu/info/legal-notices",
    terms_allowed_hosts: ["www.euipo.europa.eu"],
    browser_allowed_hosts: ["euipo.europa.eu", "www.euipo.europa.eu"],
    compliance_note: "Use one visible, user-triggered Vienna-classification query; no unattended pagination.",
  },
});

const NATIONAL_REGISTRIES = Object.freeze({
  DE: {
    authority: "German Patent and Trade Mark Office (DPMA)",
    search_url: "https://register.dpma.de/DPMAregister/Uebersicht",
    terms_url: "https://register.dpma.de/DPMAregister/service/nutzungsbedingungenpage",
    terms_allowed_hosts: ["register.dpma.de"],
    browser_allowed_hosts: ["register.dpma.de", "dpma.de", "www.dpma.de"],
    right_types: ["patent", "utility_model", "design", "trademark_word", "trademark_figurative"],
  },
  FR: {
    authority: "Institut national de la propriété industrielle (INPI)",
    search_url: "https://data.inpi.fr/",
    terms_url: "https://data.inpi.fr/content/editorial/cgu",
    terms_allowed_hosts: ["data.inpi.fr"],
    browser_allowed_hosts: ["data.inpi.fr", "inpi.fr", "www.inpi.fr"],
    right_types: ["patent", "utility_model", "design", "trademark_word", "trademark_figurative"],
  },
  IT: {
    authority: "Ufficio Italiano Brevetti e Marchi (UIBM)",
    search_url: "https://www.uibm.gov.it/bancadati/home/index/",
    terms_url: "https://www.uibm.gov.it/bancadati/index.php",
    terms_allowed_hosts: ["www.uibm.gov.it"],
    browser_allowed_hosts: ["www.uibm.gov.it", "uibm.gov.it", "uibm.mimit.gov.it"],
    right_types: ["patent", "utility_model", "design", "trademark_word", "trademark_figurative"],
  },
  ES: {
    authority: "Oficina Española de Patentes y Marcas (OEPM)",
    search_url: "https://consultas2.oepm.es/",
    terms_url: "https://www.oepm.es/es/avisos-legales/",
    terms_allowed_hosts: ["www.oepm.es"],
    browser_allowed_hosts: ["consultas2.oepm.es", "sede.oepm.gob.es", "oepm.es", "www.oepm.es"],
    right_types: ["patent", "utility_model", "design", "trademark_word", "trademark_figurative"],
  },
  GB: {
    authority: "UK Intellectual Property Office (UKIPO)",
    search_url: "https://www.gov.uk/search-for-patent",
    terms_url: "https://www.gov.uk/help/terms-conditions",
    terms_allowed_hosts: ["www.gov.uk"],
    browser_allowed_hosts: [
      "www.gov.uk", "gov.uk", "www.ipo.gov.uk", "ipo.gov.uk", "trademarks.ipo.gov.uk",
      "www.registered-design.service.gov.uk", "registered-design.service.gov.uk", "patents.service.gov.uk",
      "www.search-for-intellectual-property.service.gov.uk", "search-for-intellectual-property.service.gov.uk",
    ],
    right_types: ["patent", "design", "trademark_word", "trademark_figurative"],
  },
  NL: {
    authority: "Netherlands Patent Office / BOIP",
    search_url: "https://mijnoctrooi.rvo.nl/fo-eregister-view/",
    terms_url: "https://mijnoctrooi.rvo.nl/fo-eregister-view/disclaimer/home.action",
    terms_allowed_hosts: ["mijnoctrooi.rvo.nl"],
    shared_register_terms_url: "https://www.boip.int/en/general-terms-and-conditions-governing-boip-online-services",
    shared_register_terms_allowed_hosts: ["www.boip.int"],
    browser_allowed_hosts: ["mijnoctrooi.rvo.nl", "rvo.nl", "www.rvo.nl", "boip.int", "www.boip.int"],
    right_types: ["patent", "trademark_word", "trademark_figurative", "design"],
  },
  BE: {
    authority: "Belgian Office for Intellectual Property / BOIP",
    search_url: "https://economie.fgov.be/en/themes/intellectual-property/intellectual-property-rights/patents/searching-patents",
    terms_url: "https://bpp.economie.fgov.be/fo-eregister-view/disclaimer/home.action",
    terms_allowed_hosts: ["bpp.economie.fgov.be"],
    shared_register_terms_url: "https://www.boip.int/en/general-terms-and-conditions-governing-boip-online-services",
    shared_register_terms_allowed_hosts: ["www.boip.int"],
    browser_allowed_hosts: ["economie.fgov.be", "bpp.economie.fgov.be", "fgov.be", "boip.int", "www.boip.int"],
    right_types: ["patent", "trademark_word", "trademark_figurative", "design"],
  },
  SE: {
    authority: "Swedish Intellectual Property Office (PRV)",
    search_url: "https://search.prv.se/",
    terms_url: "https://www.prv.se/en/about-us/about-our-website/",
    terms_allowed_hosts: ["www.prv.se"],
    browser_allowed_hosts: ["search.prv.se", "prv.se", "www.prv.se"],
    right_types: ["patent", "design", "trademark_word", "trademark_figurative"],
  },
  PL: {
    authority: "Patent Office of the Republic of Poland (UPRP)",
    search_url: "https://ewyszukiwarka.pue.uprp.gov.pl/",
    terms_url: "https://uprp.gov.pl/en/node/1000610",
    terms_allowed_hosts: ["uprp.gov.pl"],
    browser_allowed_hosts: ["ewyszukiwarka.pue.uprp.gov.pl", "pue.uprp.gov.pl", "uprp.gov.pl", "www.uprp.gov.pl"],
    right_types: ["patent", "utility_model", "design", "trademark_word", "trademark_figurative"],
  },
});

const PUBLIC_WEB_SOURCES = Object.freeze({
  US: {
    authority: "United States public IP records",
    urls: {
      copyright: "https://publicrecords.copyright.gov/",
      enforcement: "https://ttabvue.uspto.gov/ttabvue/",
      copyright_records: "https://publicrecords.copyright.gov/",
      ttabvue: "https://ttabvue.uspto.gov/ttabvue/",
      ptab: "https://ptab.uspto.gov/",
      copyright_claims_board: "https://ccb.gov/",
    },
    source_keys: {
      copyright: ["copyright_records"],
      enforcement: ["ttabvue", "ptab", "copyright_claims_board"],
    },
    source_hosts: {
      copyright_records: ["publicrecords.copyright.gov", "cocatalog.loc.gov", "copyright.gov", "www.copyright.gov"],
      ttabvue: ["ttabvue.uspto.gov"],
      ptab: ["ptab.uspto.gov"],
      copyright_claims_board: ["ccb.gov", "www.ccb.gov", "dockets.ccb.gov"],
    },
    terms: {
      copyright: { url: "https://www.copyright.gov/about/legal.html", hosts: ["www.copyright.gov"] },
      copyright_records: { url: "https://www.copyright.gov/about/legal.html", hosts: ["www.copyright.gov"] },
      enforcement: { url: "https://www.uspto.gov/terms-use-uspto-websites", hosts: ["www.uspto.gov"] },
      ttabvue: { url: "https://www.uspto.gov/terms-use-uspto-websites", hosts: ["www.uspto.gov"] },
      ptab: { url: "https://www.uspto.gov/terms-use-uspto-websites", hosts: ["www.uspto.gov"] },
      copyright_claims_board: { url: "https://ccb.gov/about/legal.html", hosts: ["ccb.gov"] },
    },
    browser_allowed_hosts: [
      "publicrecords.copyright.gov", "cocatalog.loc.gov", "copyright.gov", "www.copyright.gov",
      "ttabvue.uspto.gov", "ptab.uspto.gov", "ccb.gov", "www.ccb.gov", "dockets.ccb.gov",
    ],
  },
  JP: {
    authority: "Japanese official copyright and IP court sources",
    urls: {
      copyright: "https://www.bunka.go.jp/english/policy/copyright/",
      enforcement: "https://www.courts.go.jp/app/hanrei_en/search1",
    },
    terms: {
      copyright: { url: "https://www.bunka.go.jp/english/about_hp/", hosts: ["www.bunka.go.jp"] },
      enforcement: { url: "https://www.courts.go.jp/english/outline/index.html", hosts: ["www.courts.go.jp"] },
    },
    browser_allowed_hosts: ["www.bunka.go.jp", "bunka.go.jp", "www.courts.go.jp", "courts.go.jp", "www.ip.courts.go.jp", "ip.courts.go.jp"],
  },
  EU: {
    authority: "European Union official IP and court sources",
    urls: { copyright: "https://euipo.europa.eu/", enforcement: "https://curia.europa.eu/" },
    terms: {
      copyright: { url: "https://www.euipo.europa.eu/info/legal-notices", hosts: ["www.euipo.europa.eu"] },
      enforcement: { url: "https://curia.europa.eu/site/jcms/d2_5166/en/legal-notice", hosts: ["curia.europa.eu"] },
    },
    browser_allowed_hosts: ["europa.eu", "curia.europa.eu", "euipo.europa.eu", "www.euipo.europa.eu"],
  },
  DE: {
    authority: "German official court sources",
    urls: { copyright: "https://www.rechtsprechung-im-internet.de/", enforcement: "https://www.rechtsprechung-im-internet.de/" },
    terms: {
      copyright: { url: "https://www.rechtsprechung-im-internet.de/jportal/portal/page/bsjrsprod.psml?cmsuri=%2Ftechnik%2Fde%2Fhilfe_1%2Fbsjrshinweise.jsp&riinav=4", hosts: ["www.rechtsprechung-im-internet.de"] },
      enforcement: { url: "https://www.rechtsprechung-im-internet.de/jportal/portal/page/bsjrsprod.psml?cmsuri=%2Ftechnik%2Fde%2Fhilfe_1%2Fbsjrshinweise.jsp&riinav=4", hosts: ["www.rechtsprechung-im-internet.de"] },
    },
    browser_allowed_hosts: ["rechtsprechung-im-internet.de", "www.rechtsprechung-im-internet.de", "bundesgerichtshof.de", "www.bundesgerichtshof.de", "dpma.de", "www.dpma.de"],
  },
  FR: {
    authority: "French official court and INPI sources",
    urls: { copyright: "https://www.courdecassation.fr/", enforcement: "https://www.courdecassation.fr/" },
    terms: {
      copyright: { url: "https://www.courdecassation.fr/conditions-generales-dutilisation-pour-la-reutilisation-des-donnees-judiciaires-ouvertes-open-data", hosts: ["www.courdecassation.fr"] },
      enforcement: { url: "https://www.courdecassation.fr/conditions-generales-dutilisation-pour-la-reutilisation-des-donnees-judiciaires-ouvertes-open-data", hosts: ["www.courdecassation.fr"] },
    },
    browser_allowed_hosts: ["courdecassation.fr", "www.courdecassation.fr", "data.inpi.fr", "inpi.fr", "www.inpi.fr"],
  },
  IT: {
    authority: "Italian official justice and UIBM sources",
    urls: { copyright: "https://www.giustizia.it/", enforcement: "https://www.giustizia.it/" },
    terms: {
      copyright: { url: "https://www.giustizia.it/giustizia/page/it/note_legali", hosts: ["www.giustizia.it"] },
      enforcement: { url: "https://www.giustizia.it/giustizia/page/it/note_legali", hosts: ["www.giustizia.it"] },
    },
    browser_allowed_hosts: ["giustizia.it", "www.giustizia.it", "uibm.gov.it", "www.uibm.gov.it", "uibm.mimit.gov.it"],
  },
  ES: {
    authority: "Spanish official judiciary and OEPM sources",
    urls: { copyright: "https://www.poderjudicial.es/", enforcement: "https://www.poderjudicial.es/" },
    terms: {
      copyright: { url: "https://www.poderjudicial.es/sede/en/Help/Aviso-Legal", hosts: ["www.poderjudicial.es"] },
      enforcement: { url: "https://www.poderjudicial.es/sede/en/Help/Aviso-Legal", hosts: ["www.poderjudicial.es"] },
    },
    browser_allowed_hosts: ["poderjudicial.es", "www.poderjudicial.es", "oepm.es", "www.oepm.es"],
  },
  GB: {
    authority: "UK official judiciary and UKIPO sources",
    urls: { copyright: "https://www.gov.uk/copyright", enforcement: "https://caselaw.nationalarchives.gov.uk/" },
    terms: {
      copyright: { url: "https://www.gov.uk/help/terms-conditions", hosts: ["www.gov.uk"] },
      enforcement: { url: "https://caselaw.nationalarchives.gov.uk/terms-of-use", hosts: ["caselaw.nationalarchives.gov.uk"] },
    },
    browser_allowed_hosts: ["gov.uk", "www.gov.uk", "judiciary.uk", "www.judiciary.uk", "ipo.gov.uk", "www.ipo.gov.uk", "caselaw.nationalarchives.gov.uk", "nationalarchives.gov.uk"],
  },
  NL: {
    authority: "Dutch official court sources",
    urls: { copyright: "https://uitspraken.rechtspraak.nl/", enforcement: "https://uitspraken.rechtspraak.nl/" },
    terms: {
      copyright: { url: "https://www.rechtspraak.nl/Paginas/disclaimer.aspx", hosts: ["www.rechtspraak.nl"] },
      enforcement: { url: "https://www.rechtspraak.nl/Paginas/disclaimer.aspx", hosts: ["www.rechtspraak.nl"] },
    },
    browser_allowed_hosts: ["rechtspraak.nl", "www.rechtspraak.nl", "uitspraken.rechtspraak.nl", "overheid.nl", "www.overheid.nl", "rvo.nl", "www.rvo.nl"],
  },
  BE: {
    authority: "Belgian official legal sources",
    urls: { copyright: "https://economie.fgov.be/", enforcement: "https://juportal.be/" },
    terms: {
      copyright: { url: "https://economie.fgov.be/en/conditions-use", hosts: ["economie.fgov.be"] },
      enforcement: { url: "https://juportal.be/home/disclaimer", hosts: ["juportal.be"] },
    },
    browser_allowed_hosts: ["economie.fgov.be", "justel.fgov.be", "fgov.be", "juportal.be", "www.juportal.be"],
  },
  SE: {
    authority: "Swedish official court sources",
    urls: { copyright: "https://www.domstol.se/", enforcement: "https://www.domstol.se/" },
    terms: {
      copyright: { url: "https://www.domstol.se/domstolsverket/om-webbplatsen-och-digitala-kanaler/oppna-data/", hosts: ["www.domstol.se"] },
      enforcement: { url: "https://www.domstol.se/domstolsverket/om-webbplatsen-och-digitala-kanaler/oppna-data/", hosts: ["www.domstol.se"] },
    },
    browser_allowed_hosts: ["domstol.se", "www.domstol.se", "search.prv.se", "prv.se", "www.prv.se"],
  },
  PL: {
    authority: "Polish official IP and government sources",
    urls: { copyright: "https://uprp.gov.pl/", enforcement: "https://orzeczenia.ms.gov.pl/" },
    terms: {
      copyright: { url: "https://uprp.gov.pl/en/node/1000610", hosts: ["uprp.gov.pl"] },
      enforcement: { url: "https://orzeczenia.ms.gov.pl/rss/courts", hosts: ["orzeczenia.ms.gov.pl"] },
    },
    browser_allowed_hosts: ["gov.pl", "www.gov.pl", "uprp.gov.pl", "www.uprp.gov.pl", "orzeczenia.ms.gov.pl", "ms.gov.pl"],
  },
});

function normalizedHost(value) {
  return String(value || "").trim().toLowerCase().replace(/^\.+|\.+$/g, "");
}

export function hostAllowed(hostname, allowedHosts) {
  const host = normalizedHost(hostname);
  return (allowedHosts || []).some((item) => {
    const allowed = normalizedHost(item);
    return host === allowed || host.endsWith(`.${allowed}`);
  });
}

function mergeConfiguredMetadata(base, configured = {}, preserveRightTypeStartUrl = false) {
  const merged = { ...base };
  if (configured.search_url) {
    let parsed;
    try {
      parsed = new URL(String(configured.search_url));
    } catch {
      throw new Error("Configured registry search_url is invalid");
    }
    if (parsed.protocol !== "https:" || !hostAllowed(parsed.hostname, base.browser_allowed_hosts)) {
      throw new Error("Configured registry search_url must remain on a built-in official HTTPS host");
    }
    if (!preserveRightTypeStartUrl) {
      merged.search_url = parsed.toString();
    }
  }
  if (configured.interaction_mode && configured.interaction_mode !== "cdp_assisted") {
    throw new Error("Registry automation cannot be upgraded beyond cdp_assisted by configuration");
  }
  return merged;
}

function nationalStartUrl(country, rightType, fallback) {
  if (["NL", "BE"].includes(country) && rightType === "design") {
    return "https://www.boip.int/en/designs-register";
  }
  if (["NL", "BE"].includes(country) && ["trademark_word", "trademark_figurative"].includes(rightType)) {
    return "https://www.boip.int/en/trademarks-register";
  }
  if (country === "GB" && ["trademark_word", "trademark_figurative"].includes(rightType)) {
    return "https://trademarks.ipo.gov.uk/ipo-tmtext";
  }
  if (country === "GB" && rightType === "design") {
    return "https://www.registered-design.service.gov.uk/find/";
  }
  return fallback;
}

function nationalTermsMetadata(country, rightType, registry) {
  if (["NL", "BE"].includes(country)
      && ["design", "trademark_word", "trademark_figurative"].includes(rightType)) {
    return {
      terms_url: registry.shared_register_terms_url,
      terms_allowed_hosts: [...(registry.shared_register_terms_allowed_hosts || [])],
    };
  }
  return {
    terms_url: registry.terms_url,
    terms_allowed_hosts: [...(registry.terms_allowed_hosts || [])],
  };
}

function publicTermsMetadata(source, rightType, sourceKey) {
  const key = sourceKey || rightType;
  const terms = source?.terms?.[key];
  if (!terms?.url || !Array.isArray(terms.hosts) || !terms.hosts.length) {
    throw new Error(`No official terms/service-notice binding is configured for public-web source: ${key}`);
  }
  return {
    terms_url: terms.url,
    terms_allowed_hosts: [...terms.hosts],
  };
}

export function getRegistryAdapter(provider, jurisdiction = "", rightType = "", config = {}, sourceKey = "") {
  const providerName = String(provider || "");
  const country = String(jurisdiction || "").toUpperCase();
  let base;
  let configured = config.providers?.[providerName] || {};
  let preserveRightTypeStartUrl = false;
  if (providerName === "official_registry_browser") {
    const national = NATIONAL_REGISTRIES[country];
    if (!national) throw new Error(`Unsupported national official registry jurisdiction: ${country || "(missing)"}`);
    const selectedSearchUrl = nationalStartUrl(country, rightType, national.search_url);
    const selectedTerms = nationalTermsMetadata(country, rightType, national);
    preserveRightTypeStartUrl = selectedSearchUrl !== national.search_url;
    base = {
      ...BASE_METADATA,
      ...national,
      ...selectedTerms,
      provider: providerName,
      jurisdictions: [country],
      search_url: selectedSearchUrl,
      right_types: national.right_types,
      operations: [
        "patent_recall", "utility_model_recall", "trademark_recall", "design_recall",
        "candidate_verification",
      ],
      compliance_note: "One user-triggered visible-browser search or record at a time; no unattended pagination.",
    };
    configured = configured.registries?.[country] || {};
  } else if (providerName === "public_web_browser") {
    const source = PUBLIC_WEB_SOURCES[country];
    const selectedSourceKey = String(sourceKey || "").trim();
    const allowedSourceKeys = source?.source_keys?.[rightType] || [];
    if (selectedSourceKey && !allowedSourceKeys.includes(selectedSourceKey)) {
      throw new Error(`Unsupported public-web source key for ${country}/${rightType}: ${selectedSourceKey}`);
    }
    const selectedUrl = source?.urls?.[selectedSourceKey || rightType];
    if (!source || !selectedUrl) {
      throw new Error(`No official public-web source is configured for ${country}/${rightType}`);
    }
    const selectedHosts = selectedSourceKey
      ? source.source_hosts?.[selectedSourceKey]
      : source.browser_allowed_hosts;
    if (!Array.isArray(selectedHosts) || !selectedHosts.length) {
      throw new Error(`No official host binding is configured for public-web source: ${selectedSourceKey}`);
    }
    base = {
      ...BASE_METADATA,
      ...source,
      ...publicTermsMetadata(source, rightType, selectedSourceKey),
      provider: providerName,
      jurisdictions: [country],
      right_types: ["copyright", "enforcement"],
      operations: ["copyright_recall", "enforcement_recall", "candidate_verification"],
      search_url: selectedUrl,
      browser_allowed_hosts: [...selectedHosts],
      ...(selectedSourceKey ? { source_key: selectedSourceKey } : {}),
      compliance_note: "Visible user-triggered official-site lookup only; no unattended search-engine crawling.",
    };
    const configuredHosts = configured.jurisdiction_allowed_hosts?.[country];
    if (configuredHosts !== undefined) {
      if (!Array.isArray(configuredHosts) || !configuredHosts.length) {
        throw new Error(`No public-web host allowlist is configured for ${country}`);
      }
      for (const host of configuredHosts) {
        if (!hostAllowed(host, source.browser_allowed_hosts)) {
          throw new Error(`Configured public-web host is outside the built-in official allowlist: ${host}`);
        }
      }
      const effectiveHosts = selectedSourceKey
        ? configuredHosts.filter((host) => hostAllowed(host, selectedHosts))
        : [...configuredHosts];
      if (!effectiveHosts.length) {
        throw new Error(`Configured public-web allowlist does not include the selected official source: ${selectedSourceKey}`);
      }
      base.browser_allowed_hosts = effectiveHosts;
    }
  } else {
    if (!GLOBAL_ADAPTERS[providerName]) throw new Error(`Unsupported registry provider: ${providerName}`);
    base = { ...GLOBAL_ADAPTERS[providerName], provider: providerName };
  }
  const adapter = mergeConfiguredMetadata(base, configured, preserveRightTypeStartUrl);
  adapter.terms_url = String(adapter.terms_url || "");
  adapter.terms_allowed_hosts = Array.isArray(adapter.terms_allowed_hosts)
    ? [...adapter.terms_allowed_hosts]
    : [];
  if (!adapter.terms_url) {
    throw new Error(`${providerName} has no official terms/service-notice URL`);
  }
  const termsUrl = new URL(adapter.terms_url);
  if (termsUrl.protocol !== "https:" || !hostAllowed(termsUrl.hostname, adapter.terms_allowed_hosts)) {
    throw new Error(`${providerName} terms/service-notice URL is outside its official HTTPS allowlist`);
  }
  if (country && !adapter.jurisdictions.includes(country)) {
    throw new Error(`${providerName} is not configured for jurisdiction ${country}`);
  }
  if (rightType && !adapter.right_types.includes(rightType)) {
    throw new Error(`${providerName} does not support right type ${rightType}`);
  }
  return Object.freeze({ ...adapter });
}

export function assertRegistryOperation(adapter, operation) {
  if (!adapter.operations.includes(operation)) {
    throw new Error(`${adapter.provider} does not support operation ${operation}`);
  }
  if (adapter.interaction_mode !== "cdp_assisted"
      || adapter.user_triggered_only !== true
      || adapter.bulk_automation !== false
      || adapter.max_records_per_command !== 1) {
    throw new Error("Registry adapter violates the assisted single-action safety policy");
  }
}

export function assertOfficialUrl(value, adapter) {
  let parsed;
  try {
    parsed = new URL(String(value || ""));
  } catch {
    throw new Error("Registry URL is invalid");
  }
  if (parsed.protocol !== "https:" || !hostAllowed(parsed.hostname, adapter.browser_allowed_hosts)) {
    throw new Error(`Registry URL must use an allowlisted official HTTPS host for ${adapter.provider}`);
  }
  return parsed;
}

export function directRecordUrl(adapter, record) {
  const cleanRecord = String(record || "").trim();
  if (adapter.provider === "epo_register_browser" && cleanRecord) {
    return `https://register.epo.org/application?number=${encodeURIComponent(cleanRecord)}`;
  }
  return adapter.search_url;
}

export function publicRegistryCatalog() {
  return {
    providers: Object.fromEntries(Object.entries(GLOBAL_ADAPTERS).map(([provider, value]) => [
      provider,
      { ...value, provider },
    ])),
    official_registry_browser: Object.fromEntries(Object.entries(NATIONAL_REGISTRIES).map(([country, value]) => [
      country,
      { ...BASE_METADATA, ...value, provider: "official_registry_browser" },
    ])),
    public_web_browser: Object.fromEntries(Object.entries(PUBLIC_WEB_SOURCES).map(([country, value]) => [
      country,
      { ...BASE_METADATA, ...value, provider: "public_web_browser" },
    ])),
  };
}
