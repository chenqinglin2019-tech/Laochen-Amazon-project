#!/usr/bin/env node

import { createHash } from "node:crypto";
import { existsSync, readFileSync, writeFileSync, mkdirSync, statSync, renameSync, unlinkSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const RULESET_VERSION = "2.0";
const SCHEMA_VERSION = "2.0";
const MODULES = [
  "appearance_design",
  "utility_patent",
  "pending_patent",
  "word_mark",
  "figurative_mark",
  "trade_dress",
  "copyright_creative_ip",
  "enforcement_public_signals",
];
const LEGACY_DISCOVERY_MODULES = [
  "appearance_design",
  "utility_patent",
  "pending_patent",
  "word_mark",
  "figurative_trade_dress",
  "copyright_creative_ip",
  "enforcement_public_signals",
];
const RISK_ORDER = ["very_low", "low", "medium", "high", "critical"];
const CONFIDENCE_ORDER = ["low", "medium", "high"];
const LEGAL_MATERIALITIES = new Set([
  "risk_bearing",
  "provenance_lead",
  "comparison_only",
  "mitigating",
  "not_material",
  "unresolved",
]);
const RECORD_KINDS = new Set([
  "right_record",
  "application",
  "enforcement_event",
  "marketplace_page",
  "creative_source",
  "comparison_material",
  "non_right_page",
]);
const AUTHORITY_TIERS = new Set([
  "official",
  "authoritative",
  "primary",
  "commercial",
  "unknown",
]);
const EVIDENCE_ROLES = new Set([
  "risk_driver",
  "provenance",
  "context",
  "mitigating",
]);
const HIGH_AUTHORITY = new Set(["official", "authoritative", "primary"]);
const AUTHORITY_ORDER = ["unknown", "commercial", "primary", "authoritative", "official"];
const NON_RIGHT_KINDS = new Set(["marketplace_page", "comparison_material", "non_right_page"]);
const LEGAL_RECORD_KINDS = new Set(["right_record", "application", "enforcement_event", "creative_source"]);
const FALLBACK_REQUIRED_RISK_FACTORS = {
  appearance_design: ["right_status", "official_record_verified", "same_product_category", "complete_official_images", "claimed_portions", "dominant_shared_features", "dominant_differences", "difference_effect", "overall_visual_impression", "authorization_status"],
  utility_patent: ["right_status", "official_record_verified", "independent_claim_mappings", "claim_scope_conclusion", "authorization_status"],
  pending_patent: ["right_status", "official_record_verified", "independent_claim_mappings", "claim_scope_conclusion", "claim_change_uncertainty", "monitoring_trigger", "authorization_status"],
  word_mark: ["right_status", "official_record_verified", "mark_similarity", "goods_services_relatedness", "channels_overlap", "consumer_overlap", "mark_strength", "confusion_likelihood", "authorization_status"],
  figurative_mark: ["right_status", "official_record_verified", "figurative_similarity", "goods_services_relatedness", "channels_overlap", "consumer_overlap", "mark_strength", "confusion_likelihood", "authorization_status"],
  trade_dress: ["identified_trade_dress_claim", "nonfunctionality", "distinctiveness", "source_identification", "confusion_likelihood", "authorization_status"],
  copyright_creative_ip: ["asset_scope", "protectable_expression", "asset_match", "expression_similarity", "creator_or_earliest_source", "ownership_reliability", "authorization_status", "commercial_use_covered"],
  enforcement_public_signals: ["event_verified", "claimant", "case_or_complaint_id", "subject_match", "procedure_status", "underlying_risk_driver_ids"],
};
const RATING_DECISION_FACTORS = {
  appearance_design: new Set(["right_status", "official_record_verified", "same_product_category", "complete_official_images", "claimed_portions", "dominant_shared_features", "dominant_differences", "difference_effect", "overall_visual_impression", "authorization_status"]),
  utility_patent: new Set(["right_status", "official_record_verified", "independent_claim_mappings", "claim_scope_conclusion", "authorization_status"]),
  pending_patent: new Set(["right_status", "official_record_verified", "independent_claim_mappings", "claim_scope_conclusion", "claim_change_uncertainty", "monitoring_trigger", "authorization_status"]),
  word_mark: new Set(["right_status", "official_record_verified", "mark_similarity", "goods_services_relatedness", "channels_overlap", "consumer_overlap", "mark_strength", "confusion_likelihood", "authorization_status"]),
  figurative_mark: new Set(["right_status", "official_record_verified", "figurative_similarity", "goods_services_relatedness", "channels_overlap", "consumer_overlap", "mark_strength", "confusion_likelihood", "authorization_status"]),
  trade_dress: new Set(["identified_trade_dress_claim", "nonfunctionality", "distinctiveness", "source_identification", "confusion_likelihood", "authorization_status"]),
  copyright_creative_ip: new Set(["asset_scope", "protectable_expression", "asset_match", "expression_similarity", "creator_or_earliest_source", "ownership_reliability", "authorization_status", "commercial_use_covered"]),
  enforcement_public_signals: new Set(["event_verified", "claimant", "case_or_complaint_id", "subject_match", "procedure_status", "underlying_risk_driver_ids"]),
};
const RISK_RECORD_KINDS = {
  appearance_design: new Set(["right_record"]),
  utility_patent: new Set(["right_record"]),
  pending_patent: new Set(["application"]),
  word_mark: new Set(["right_record"]),
  figurative_mark: new Set(["right_record"]),
  trade_dress: new Set(["right_record", "creative_source"]),
  copyright_creative_ip: new Set(["right_record", "creative_source"]),
  enforcement_public_signals: new Set(["enforcement_event"]),
};
const scriptPath = fileURLToPath(import.meta.url);
const scriptDir = dirname(scriptPath);
const skillDir = resolve(scriptDir, "..");
let rulesDescriptorCache = null;

class InputError extends Error {
  constructor(message, code = "INVALID_INPUT") {
    super(message);
    this.name = "InputError";
    this.code = code;
  }
}

function parseArgs(argv) {
  const positional = [];
  const options = {};
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith("--")) {
      positional.push(token);
      continue;
    }
    const key = token.slice(2);
    if (["dry-run", "json"].includes(key)) {
      options[key] = true;
      continue;
    }
    if (i + 1 >= argv.length || argv[i + 1].startsWith("--")) {
      throw new InputError(`--${key} requires a value`, "ARGUMENT_REQUIRED");
    }
    options[key] = argv[i + 1];
    i += 1;
  }
  return { positional, options };
}

function readJson(path, label = "JSON") {
  let parsed;
  try {
    parsed = JSON.parse(readFileSync(path, "utf8"));
  } catch (error) {
    throw new InputError(`${label} cannot be read: ${path}: ${error.message}`, "JSON_READ_FAILED");
  }
  return parsed;
}

function writeJson(path, value) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function sha256(value) {
  const data = typeof value === "string" || Buffer.isBuffer(value)
    ? value
    : JSON.stringify(value);
  return createHash("sha256").update(data).digest("hex");
}

function now() {
  return new Date().toISOString();
}

function array(value) {
  return Array.isArray(value) ? value : [];
}

function nonBlankString(value) {
  return typeof value === "string" && value.trim().length > 0;
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonicalize(value[key])]));
  }
  return value;
}

function sameJson(left, right) {
  return JSON.stringify(canonicalize(left)) === JSON.stringify(canonicalize(right));
}

const UNSAFE_PATH_SEGMENTS = new Set(["__proto__", "prototype", "constructor"]);

function factorPathSegments(candidate, path) {
  const keys = String(path).split(".");
  if (keys.length < 2 || keys[0] !== "factors"
    || keys.some((key) => key.length === 0 || UNSAFE_PATH_SEGMENTS.has(key))) {
    throw new InputError(`invalid factor path: ${path}`, "REVIEW_FACT_PATH_INVALID");
  }
  if (!requiredRiskFactors(candidate.module).includes(keys[1])) {
    throw new InputError(`factor path is not rating material for ${candidate.module}: ${path}`, "REVIEW_FACT_PATH_INVALID");
  }
  let cursor = candidate;
  for (const key of keys) {
    if (Array.isArray(cursor)) {
      if (!/^\d+$/.test(key) || Number(key) >= cursor.length) {
        throw new InputError(`factor path does not exist: ${path}`, "REVIEW_FACT_PATH_INVALID");
      }
    } else if (!cursor || typeof cursor !== "object" || !Object.hasOwn(cursor, key)) {
      throw new InputError(`factor path does not exist: ${path}`, "REVIEW_FACT_PATH_INVALID");
    }
    cursor = cursor[key];
  }
  return keys;
}

function isRatingDecisionPath(module, path) {
  const keys = String(path).split(".");
  return keys[0] === "factors" && RATING_DECISION_FACTORS[module]?.has(keys[1]) === true;
}

function factorValueAtPath(candidate, path) {
  return factorPathSegments(candidate, path).reduce((value, key) => value[key], candidate);
}

function setFactorValueAtPath(candidate, path, value) {
  const keys = factorPathSegments(candidate, path);
  let cursor = candidate;
  for (const key of keys.slice(0, -1)) cursor = cursor[key];
  cursor[keys.at(-1)] = value;
}

function immutableArtifactDigest(value) {
  const artifact = { ...value };
  delete artifact.digest;
  return sha256(canonicalize(artifact));
}

function stableDigest(value) {
  return sha256(canonicalize(value));
}

function bool(value) {
  return value === true;
}

function factor(candidate, key, fallback = "unknown") {
  return candidate?.factors?.[key] ?? fallback;
}

function candidateSummary(candidate) {
  const summary = {
    candidate_id: candidate.candidate_id,
    module: candidate.module,
    record_kind: candidate.record_kind,
    legal_materiality: candidate.legal_materiality,
    risk_driver_eligible: candidate.risk_driver_eligible === true,
    authority_tier: candidate.authority_tier,
    evidence_role: candidate.evidence_role,
    evidence_refs: [...array(candidate.evidence_refs)],
    verification_refs: [...array(candidate.verification_refs)],
    evidence_cluster_id: candidate.evidence_cluster_id,
    duplicate_of: candidate.duplicate_of ?? null,
    independence_group: candidate.independence_group,
    factors: candidate.factors && typeof candidate.factors === "object" ? { ...candidate.factors } : {},
  };
  for (const key of [
    "legacy_module",
    "legacy_disposition",
    "legacy_reassessed",
    "target_jurisdiction",
    "source_jurisdiction",
    "right_jurisdiction",
    "record_number",
    "title",
    "owner",
    "source_locator",
    "published_at",
    "first_seen_at",
  ]) {
    if (candidate[key] !== undefined) summary[key] = candidate[key];
  }
  return summary;
}

function minConfidence(...values) {
  const normalized = values.filter((value) => CONFIDENCE_ORDER.includes(value));
  if (normalized.length === 0) return "low";
  return normalized.reduce((minimum, value) => (
    CONFIDENCE_ORDER.indexOf(value) < CONFIDENCE_ORDER.indexOf(minimum) ? value : minimum
  ));
}

function maxRisk(...values) {
  const normalized = values.filter((value) => RISK_ORDER.includes(value));
  if (normalized.length === 0) return "not_assessable";
  return normalized.reduce((maximum, value) => (
    RISK_ORDER.indexOf(value) > RISK_ORDER.indexOf(maximum) ? value : maximum
  ));
}

function authorityConfidence(candidate) {
  const tier = candidate.authority_tier;
  if (HIGH_AUTHORITY.has(tier) && array(candidate.verification_refs).length > 0) return "high";
  if (HIGH_AUTHORITY.has(tier)) return "medium";
  return "low";
}

function highEvidenceGate(candidate) {
  return HIGH_AUTHORITY.has(candidate.authority_tier)
    && array(candidate.evidence_refs).length > 0
    && array(candidate.verification_refs).length > 0;
}

function candidateResult(candidate, risk, basisCodes, { confidenceCap = null } = {}) {
  let finalRisk = risk;
  const codes = [...basisCodes];
  let confidence = authorityConfidence(candidate);
  if (["high", "critical"].includes(finalRisk) && !highEvidenceGate(candidate)) {
    finalRisk = "medium";
    codes.push("HIGH_EVIDENCE_GATE_NOT_MET");
    confidence = "low";
  }
  if (confidenceCap) confidence = minConfidence(confidence, confidenceCap);
  return {
    candidate_id: candidate.candidate_id,
    module: candidate.module,
    legal_risk: finalRisk,
    risk_confidence: confidence,
    basis_codes: codes,
    evidence_cluster_id: candidate.evidence_cluster_id,
    independence_group: candidate.independence_group,
  };
}

function compareCandidateEntries(left, right) {
  for (const difference of [
    CONFIDENCE_ORDER.indexOf(left.result.risk_confidence) - CONFIDENCE_ORDER.indexOf(right.result.risk_confidence),
    AUTHORITY_ORDER.indexOf(left.candidate.authority_tier) - AUTHORITY_ORDER.indexOf(right.candidate.authority_tier),
    array(left.candidate.verification_refs).length - array(right.candidate.verification_refs).length,
    array(left.candidate.evidence_refs).length - array(right.candidate.evidence_refs).length,
  ]) {
    if (difference !== 0) return difference;
  }
  return right.candidate.candidate_id.localeCompare(left.candidate.candidate_id);
}

function sameRatingFact(left, right) {
  const normalize = (value) => {
    if (typeof value === "string") return value.normalize("NFKC").trim().replace(/\s+/g, " ");
    if (Array.isArray(value)) {
      return value.map(normalize).sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
    }
    if (value && typeof value === "object") {
      return Object.fromEntries(Object.keys(value).sort().map((key) => [key, normalize(value[key])]));
    }
    return value;
  };
  return JSON.stringify(normalize(left)) === JSON.stringify(normalize(right));
}

function duplicateRatingFactConflicts(candidates) {
  const groups = new Map();
  for (const candidate of candidates.filter(isRatingRelevantCandidate)) {
    const key = `${candidate.module}:${candidate.evidence_cluster_id}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(candidate);
  }
  const conflicts = [];
  for (const group of groups.values()) {
    if (group.length < 2) continue;
    const ordered = [...group].sort((left, right) => left.candidate_id.localeCompare(right.candidate_id));
    const canonical = ordered[0];
    for (const factorName of RATING_DECISION_FACTORS[canonical.module]) {
      const mismatch = ordered.slice(1).find((candidate) => (
        !sameRatingFact(canonical.factors[factorName], candidate.factors[factorName])
      ));
      if (!mismatch) continue;
      conflicts.push({
        conflict_id: `CLUSTER-CONFLICT-${sha256(`${canonical.module}:${canonical.evidence_cluster_id}:${factorName}`).slice(0, 24)}`,
        module: canonical.module,
        candidate_id: canonical.candidate_id,
        fact_path: `factors.${factorName}`,
        first_review_value: canonical.factors[factorName],
        second_review_value: mismatch.factors[factorName],
        rating_material: true,
        status: "unresolved",
      });
    }
  }
  return conflicts;
}

function isAuthorized(value) {
  return ["authorized", "owned", "public_domain", "not_required"].includes(value);
}

function isLegallyTestedExclusionCandidate(candidate) {
  return ["comparison_only", "not_material", "mitigating", "provenance_lead"].includes(candidate?.legal_materiality)
    && RISK_RECORD_KINDS[candidate?.module]?.has(candidate?.record_kind) === true;
}

function isRatingRelevantCandidate(candidate) {
  return (candidate?.legal_materiality === "risk_bearing" && candidate?.risk_driver_eligible === true)
    || isLegallyTestedExclusionCandidate(candidate);
}

function evaluateAppearance(candidate) {
  const visual = factor(candidate, "overall_visual_impression", "unknown");
  const differenceEffect = factor(candidate, "difference_effect", "unknown");
  const authorization = factor(candidate, "authorization_status", "unknown");
  const status = factor(candidate, "right_status", "unknown");
  if (isAuthorized(authorization)) return candidateResult(candidate, "low", ["AUTHORIZED_OR_OWNED"]);
  if (["expired", "cancelled", "abandoned", "rejected", "not_found"].includes(status)) {
    if (!bool(factor(candidate, "official_record_verified", false))) {
      return candidateResult(candidate, "not_assessable", ["INACTIVE_RIGHT_STATUS_NOT_VERIFIED"], { confidenceCap: "low" });
    }
    return candidateResult(candidate, "low", ["RIGHT_INACTIVE_OR_NOT_FOUND"]);
  }
  if (!bool(factor(candidate, "complete_official_images", false)) || visual === "unknown" || differenceEffect === "unknown") {
    return candidateResult(candidate, "not_assessable", ["DESIGN_IMAGE_OR_IMPRESSION_NOT_ASSESSED"], { confidenceCap: "low" });
  }
  if (differenceEffect === "decisive") {
    return candidateResult(candidate, "low", ["DECISIVE_DESIGN_DIFFERENCES"]);
  }
  if (["none", "low", "different"].includes(visual)) return candidateResult(candidate, "low", ["OVERALL_VISUAL_IMPRESSION_LOW"], { confidenceCap: status === "unknown" ? "low" : null });
  const strongOverlap = ["high", "exact"].includes(visual)
    && bool(factor(candidate, "same_product_category", false))
    && bool(factor(candidate, "complete_official_images", false))
    && array(factor(candidate, "claimed_portions", [])).length > 0
    && array(factor(candidate, "dominant_shared_features", [])).length > 0
    && ["none", "non_decisive"].includes(differenceEffect);
  const verifiedActive = bool(factor(candidate, "official_record_verified", false))
    && status === "active";
  if (strongOverlap && verifiedActive) {
    if (authorization === "unlicensed") {
      return candidateResult(candidate, "high", ["VERIFIED_ACTIVE_RIGHT", "OVERALL_VISUAL_IMPRESSION_HIGH", "UNLICENSED_USE_VERIFIED"]);
    }
    return candidateResult(candidate, "medium", ["VERIFIED_ACTIVE_RIGHT", "OVERALL_VISUAL_IMPRESSION_HIGH", "AUTHORIZATION_UNRESOLVED"], { confidenceCap: "low" });
  }
  if (["medium", "high", "exact"].includes(visual)) {
    return candidateResult(candidate, "medium", ["MEANINGFUL_VISUAL_OVERLAP_UNRESOLVED"], { confidenceCap: "low" });
  }
  return candidateResult(candidate, "low", ["NO_SUBSTANTIATED_DESIGN_OVERLAP"]);
}

function evaluatePatent(candidate, pending = false) {
  const mapping = factor(candidate, "claim_scope_conclusion", factor(candidate, "claim_mapping", "not_reviewed"));
  const status = factor(candidate, "right_status", "unknown");
  const authorization = factor(candidate, "authorization_status", "unknown");
  const verified = bool(factor(candidate, "official_record_verified", false));
  if (isAuthorized(authorization)) return candidateResult(candidate, "low", ["AUTHORIZED_OR_OWNED"]);
  if (["expired", "cancelled", "abandoned", "rejected", "not_found"].includes(status)) {
    if (!verified) {
      return candidateResult(candidate, "not_assessable", ["INACTIVE_RIGHT_STATUS_NOT_VERIFIED"], { confidenceCap: "low" });
    }
    return candidateResult(candidate, "low", ["RIGHT_INACTIVE_OR_NOT_FOUND"]);
  }
  if (["none", "missing_elements"].includes(mapping)) {
    return candidateResult(candidate, "low", ["NO_CLAIM_ELEMENT_COVERAGE"]);
  }
  const claimMappings = array(factor(candidate, "independent_claim_mappings", []));
  const completeMapping = claimMappings.some((claim) => {
    const required = array(claim.required_elements);
    const mapped = new Set(array(claim.mapped_elements));
    return required.length > 0
      && required.every((element) => mapped.has(element))
      && claim.mapping_status === "complete"
      && array(claim.missing_elements).length === 0;
  });
  if (!pending && verified && status === "active" && mapping === "all_elements_mapped" && completeMapping) {
    if (authorization === "unlicensed") {
      return candidateResult(candidate, "high", ["ACTIVE_PATENT", "ALL_ELEMENTS_MAPPED", "UNLICENSED_USE_VERIFIED"]);
    }
    return candidateResult(candidate, "medium", ["ACTIVE_PATENT", "ALL_ELEMENTS_MAPPED", "AUTHORIZATION_UNRESOLVED"], { confidenceCap: "low" });
  }
  if (mapping === "not_reviewed") {
    return candidateResult(candidate, "not_assessable", ["CLAIM_MAPPING_NOT_REVIEWED"], { confidenceCap: "low" });
  }
  const meaningfulMapping = claimMappings.some((claim) => (
    array(claim.mapped_elements).length > 0 && ["complete", "partial"].includes(claim.mapping_status)
  ));
  if (["all_elements_mapped", "uncertain"].includes(mapping) && meaningfulMapping) {
    if (pending) {
      const changeUncertainty = factor(candidate, "claim_change_uncertainty", "unknown");
      const monitoringTrigger = factor(candidate, "monitoring_trigger", null);
      const monitoringReady = ["low", "medium"].includes(changeUncertainty)
        && typeof monitoringTrigger === "string"
        && monitoringTrigger.trim().length > 0;
      return candidateResult(
        candidate,
        "medium",
        monitoringReady
          ? ["PENDING_CLAIM_OVERLAP", "PENDING_MONITORING_DEFINED"]
          : ["PENDING_CLAIM_OVERLAP", "PENDING_CLAIM_MONITORING_UNRESOLVED"],
        { confidenceCap: monitoringReady && completeMapping ? "medium" : "low" },
      );
    }
    return candidateResult(candidate, "medium", ["CLAIM_SCOPE_UNRESOLVED"], { confidenceCap: "low" });
  }
  if (["all_elements_mapped", "uncertain"].includes(mapping)) {
    return candidateResult(candidate, "not_assessable", ["CLAIM_MAPPING_EVIDENCE_INSUFFICIENT"], { confidenceCap: "low" });
  }
  return candidateResult(candidate, "low", ["NO_SUBSTANTIATED_CLAIM_OVERLAP"]);
}

function evaluateMark(candidate) {
  const authorization = factor(candidate, "authorization_status", "unknown");
  if (isAuthorized(authorization)) return candidateResult(candidate, "low", ["AUTHORIZED_OR_OWNED"]);
  const similarity = candidate.module === "figurative_mark"
    ? factor(candidate, "figurative_similarity", "none")
    : factor(candidate, "mark_similarity", "none");
  const relatedness = factor(candidate, "goods_services_relatedness", "none");
  const status = factor(candidate, "right_status", "unknown");
  if (["expired", "cancelled", "abandoned", "rejected", "not_found"].includes(status)) {
    if (!bool(factor(candidate, "official_record_verified", false))) {
      return candidateResult(candidate, "not_assessable", ["INACTIVE_RIGHT_STATUS_NOT_VERIFIED"], { confidenceCap: "low" });
    }
    return candidateResult(candidate, "low", ["RIGHT_INACTIVE_OR_NOT_FOUND"]);
  }
  if (["none", "low"].includes(relatedness) || ["none", "low", "different"].includes(similarity)) {
    return candidateResult(candidate, "low", ["GOODS_SERVICES_UNRELATED"]);
  }
  if (similarity === "unknown" || relatedness === "unknown") {
    return candidateResult(candidate, "not_assessable", ["MARK_CONFUSION_FACTS_NOT_ASSESSED"], { confidenceCap: "low" });
  }
  const verifiedActive = bool(factor(candidate, "official_record_verified", false))
    && status === "active";
  const confusion = factor(candidate, "confusion_likelihood", "unknown");
  const strength = factor(candidate, "mark_strength", "unknown");
  const confusionFactors = bool(factor(candidate, "channels_overlap", false))
    && bool(factor(candidate, "consumer_overlap", false));
  if (verifiedActive
    && ["near_exact", "high", "exact"].includes(similarity)
    && relatedness === "high"
    && confusionFactors
    && confusion === "high"
    && ["strong", "medium"].includes(strength)) {
    if (authorization === "unlicensed") {
      return candidateResult(candidate, "high", ["ACTIVE_MARK", "LIKELIHOOD_OF_CONFUSION_FACTORS_STRONG", "UNLICENSED_USE_VERIFIED"]);
    }
    return candidateResult(candidate, "medium", ["ACTIVE_MARK", "LIKELIHOOD_OF_CONFUSION_FACTORS_STRONG", "AUTHORIZATION_UNRESOLVED"], { confidenceCap: "low" });
  }
  if (["medium", "near_exact", "high", "exact"].includes(similarity)
    && ["high", "medium"].includes(relatedness)
    && ["medium", "high", "unknown"].includes(confusion)) {
    return candidateResult(candidate, "medium", ["POTENTIAL_MARK_CONFUSION_UNRESOLVED"], { confidenceCap: "low" });
  }
  return candidateResult(candidate, "low", ["NO_SUBSTANTIATED_MARK_CONFLICT"]);
}

function evaluateTradeDress(candidate) {
  const authorization = factor(candidate, "authorization_status", "unknown");
  if (isAuthorized(authorization)) return candidateResult(candidate, "low", ["AUTHORIZED_OR_OWNED"]);
  const confusion = factor(candidate, "confusion_likelihood", "none");
  const claim = Boolean(factor(candidate, "identified_trade_dress_claim", null));
  const nonfunctional = ["established", "supported"].includes(factor(candidate, "nonfunctionality"));
  const distinctive = ["established", "supported"].includes(factor(candidate, "distinctiveness"));
  const sourceUse = ["established", "supported"].includes(factor(candidate, "source_identification"));
  const unknownProtectability = ["nonfunctionality", "distinctiveness", "source_identification"]
    .some((key) => factor(candidate, key) === "unknown");
  if (confusion === "unknown") {
    return candidateResult(candidate, "not_assessable", ["TRADE_DRESS_CONFUSION_NOT_ASSESSED"], { confidenceCap: "low" });
  }
  if (claim && nonfunctional && distinctive && sourceUse && confusion === "high") {
    if (authorization === "unlicensed") {
      return candidateResult(candidate, "high", ["TRADE_DRESS_ELEMENTS_SUPPORTED", "CONFUSION_STRONG", "UNLICENSED_USE_VERIFIED"]);
    }
    return candidateResult(candidate, "medium", ["TRADE_DRESS_ELEMENTS_SUPPORTED", "CONFUSION_STRONG", "AUTHORIZATION_UNRESOLVED"], { confidenceCap: "low" });
  }
  const supported = [claim, nonfunctional, distinctive, sourceUse].filter(Boolean).length;
  if (claim && supported >= 2 && ["medium", "high"].includes(confusion)) {
    return candidateResult(candidate, "medium", ["TRADE_DRESS_FACTS_INCOMPLETE"], { confidenceCap: "low" });
  }
  if (claim && unknownProtectability && ["medium", "high"].includes(confusion)) {
    return candidateResult(candidate, "medium", ["TRADE_DRESS_PROTECTABILITY_UNRESOLVED"], { confidenceCap: "low" });
  }
  return candidateResult(candidate, "low", ["NO_PROTECTABLE_TRADE_DRESS_SHOWING"]);
}

function evaluateCopyright(candidate) {
  const authorization = factor(candidate, "authorization_status", "unknown");
  if (isAuthorized(authorization)) return candidateResult(candidate, "low", ["AUTHORIZED_OR_OWNED"]);
  const protectable = factor(candidate, "protectable_expression", "uncertain");
  const match = factor(candidate, "asset_match", "uncertain");
  const similarity = factor(candidate, "expression_similarity", "none");
  const ownership = factor(candidate, "ownership_reliability", "unknown");
  if (["none", "weak"].includes(protectable) || ["none", "low", "different"].includes(match) || ["none", "low", "different"].includes(similarity)) {
    return candidateResult(candidate, "low", ["NO_PROTECTABLE_EXPRESSION_OVERLAP"]);
  }
  if (similarity === "unknown" && ["medium", "high", "near_exact", "exact"].includes(match)
    && ["established", "likely", "unknown"].includes(protectable)) {
    return candidateResult(candidate, "medium", ["COPYRIGHT_EXPRESSION_COMPARISON_UNRESOLVED"], { confidenceCap: "low" });
  }
  if (similarity === "unknown" || match === "unknown") {
    return candidateResult(candidate, "not_assessable", ["COPYRIGHT_EXPRESSION_NOT_ASSESSED"], { confidenceCap: "low" });
  }
  if (protectable === "established"
    && ["high", "near_exact", "exact"].includes(match)
    && ["high", "near_exact", "exact"].includes(similarity)
    && ["high", "verified"].includes(ownership)
    && !["unknown", null, ""].includes(factor(candidate, "asset_scope", "unknown"))
    && Boolean(factor(candidate, "creator_or_earliest_source", null))
    && factor(candidate, "commercial_use_covered", "unknown") === false
    && authorization === "unlicensed") {
    return candidateResult(candidate, "high", ["PROTECTABLE_EXPRESSION_MATCH", "UNLICENSED_USE_VERIFIED"]);
  }
  if (["established", "likely", "unknown"].includes(protectable)
    && ["medium", "high", "near_exact", "exact", "unknown"].includes(match)
    && ["medium", "high", "near_exact", "exact"].includes(similarity)) {
    return candidateResult(candidate, "medium", ["COPYRIGHT_PROVENANCE_UNRESOLVED"], { confidenceCap: "low" });
  }
  return candidateResult(candidate, "low", ["NO_SUBSTANTIATED_COPYRIGHT_CONFLICT"]);
}

function evaluateEnforcement(candidate) {
  const verified = bool(factor(candidate, "event_verified", false));
  const subject = factor(candidate, "subject_match", "none");
  const status = factor(candidate, "procedure_status", "none");
  if (!verified) {
    return candidateResult(candidate, "not_assessable", ["ENFORCEMENT_EVENT_NOT_VERIFIED"], { confidenceCap: "low" });
  }
  if (["closed", "dismissed"].includes(status)) {
    return candidateResult(candidate, "low", ["ENFORCEMENT_PROCEDURE_TERMINATED"]);
  }
  if (["none", "partial"].includes(subject)) {
    return candidateResult(candidate, "low", ["NO_VERIFIED_TARGETED_ENFORCEMENT"]);
  }
  const eventBound = Boolean(factor(candidate, "claimant", null))
    && Boolean(factor(candidate, "case_or_complaint_id", null))
    && array(factor(candidate, "underlying_risk_driver_ids", [])).length > 0;
  if (["strong", "exact"].includes(subject)
    && ["active_complaint", "active_litigation", "platform_enforcement", "active_tro", "active_injunction"].includes(status)
    && eventBound) {
    return candidateResult(candidate, "critical", ["VERIFIED_ENFORCEMENT_EVENT", "EXACT_SUBJECT_MATCH", "ACTIVE_PROCEDURE"]);
  }
  if (["strong", "exact"].includes(subject)
    && ["active_complaint", "active_litigation", "platform_enforcement", "active_tro", "active_injunction"].includes(status)) {
    return candidateResult(candidate, "medium", ["VERIFIED_ENFORCEMENT_EVENT", "ACTIVE_PROCEDURE", "ENFORCEMENT_BINDING_INCOMPLETE"], { confidenceCap: "low" });
  }
  if (["strong", "exact"].includes(subject) && status === "unknown") {
    return candidateResult(candidate, "medium", ["ENFORCEMENT_STATUS_UNRESOLVED"], { confidenceCap: "low" });
  }
  return candidateResult(candidate, "medium", ["ENFORCEMENT_SUBJECT_OR_STATUS_UNRESOLVED"], { confidenceCap: "low" });
}

function evaluateCandidate(candidate) {
  switch (candidate.module) {
    case "appearance_design": return evaluateAppearance(candidate);
    case "utility_patent": return evaluatePatent(candidate, false);
    case "pending_patent": return evaluatePatent(candidate, true);
    case "word_mark":
    case "figurative_mark": return evaluateMark(candidate);
    case "trade_dress": return evaluateTradeDress(candidate);
    case "copyright_creative_ip": return evaluateCopyright(candidate);
    case "enforcement_public_signals": return evaluateEnforcement(candidate);
    default: throw new InputError(`unsupported module: ${candidate.module}`, "MODULE_UNSUPPORTED");
  }
}

function validateRiskFactors(candidate, prefix) {
  const factors = candidate.factors;
  const fail = (key) => {
    throw new InputError(`${prefix}.factors.${key} is invalid`, "MODULE_FACTOR_INVALID");
  };
  const enumValue = (key, values) => {
    if (!values.includes(factors[key])) fail(key);
  };
  const booleanValue = (key) => {
    if (typeof factors[key] !== "boolean") fail(key);
  };
  const booleanOrUnknown = (key) => {
    if (typeof factors[key] !== "boolean" && factors[key] !== "unknown") fail(key);
  };
  const nullableString = (key) => {
    if (factors[key] !== null && !nonBlankString(factors[key])) fail(key);
  };
  const stringArray = (key, { nonEmpty = false } = {}) => {
    const value = factors[key];
    if (!Array.isArray(value) || (nonEmpty && value.length === 0)
      || value.some((item) => !nonBlankString(item))
      || new Set(value).size !== value.length) fail(key);
  };
  const allowedKeys = (keys) => {
    const extras = Object.keys(factors).filter((key) => !keys.includes(key));
    if (extras.length > 0) fail(extras[0]);
  };
  const rightStatuses = ["active", "pending", "expired", "cancelled", "abandoned", "rejected", "disputed", "unknown", "not_found", "not_applicable"];
  const authorizationStatuses = ["authorized", "unlicensed", "unknown", "not_applicable"];
  const gradedSimilarity = ["exact", "near_exact", "high", "medium", "low", "none", "different", "unknown"];
  const relatedness = ["high", "medium", "low", "none", "unknown"];

  if (candidate.module === "appearance_design") {
    allowedKeys(["right_status", "official_record_verified", "same_product_category", "complete_official_images", "retrieval_similarity_score", "claimed_portions", "dominant_shared_features", "dominant_differences", "difference_effect", "overall_visual_impression", "authorization_status"]);
    enumValue("right_status", rightStatuses);
    booleanValue("official_record_verified");
    booleanOrUnknown("same_product_category");
    booleanValue("complete_official_images");
    stringArray("claimed_portions", { nonEmpty: true });
    stringArray("dominant_shared_features", { nonEmpty: true });
    stringArray("dominant_differences");
    enumValue("difference_effect", ["none", "non_decisive", "decisive", "unknown"]);
    enumValue("overall_visual_impression", ["exact", "high", "medium", "low", "none", "different", "unknown"]);
    enumValue("authorization_status", authorizationStatuses);
    if (Object.hasOwn(factors, "retrieval_similarity_score")
      && (typeof factors.retrieval_similarity_score !== "number" || factors.retrieval_similarity_score < 0 || factors.retrieval_similarity_score > 1)) fail("retrieval_similarity_score");
    return;
  }

  if (["utility_patent", "pending_patent"].includes(candidate.module)) {
    allowedKeys(["right_status", "official_record_verified", "independent_claim_mappings", "claim_scope_conclusion", "claim_change_uncertainty", "monitoring_trigger", "authorization_status"]);
    enumValue("right_status", rightStatuses);
    booleanValue("official_record_verified");
    if (!Array.isArray(factors.independent_claim_mappings) || factors.independent_claim_mappings.length === 0) fail("independent_claim_mappings");
    for (const [index, mapping] of factors.independent_claim_mappings.entries()) {
      if (!mapping || typeof mapping !== "object") fail(`independent_claim_mappings[${index}]`);
      const keys = Object.keys(mapping);
      if (["claim_id", "required_elements", "mapped_elements", "missing_elements", "mapping_status"].some((key) => !keys.includes(key))
        || keys.some((key) => !["claim_id", "required_elements", "mapped_elements", "missing_elements", "mapping_status"].includes(key))
        || !nonBlankString(mapping.claim_id)
        || !Array.isArray(mapping.required_elements) || mapping.required_elements.length === 0
        || !Array.isArray(mapping.mapped_elements) || !Array.isArray(mapping.missing_elements)
        || [...mapping.required_elements, ...mapping.mapped_elements, ...mapping.missing_elements].some((item) => !nonBlankString(item))
        || !["complete", "partial", "unmapped", "unknown"].includes(mapping.mapping_status)) fail(`independent_claim_mappings[${index}]`);
      const mapped = new Set(mapping.mapped_elements);
      const actuallyComplete = mapping.required_elements.every((element) => mapped.has(element))
        && mapping.missing_elements.length === 0;
      if ((mapping.mapping_status === "complete") !== actuallyComplete) fail(`independent_claim_mappings[${index}].mapping_status`);
    }
    enumValue("claim_scope_conclusion", ["all_elements_mapped", "missing_elements", "uncertain", "not_reviewed"]);
    const hasCompleteClaim = factors.independent_claim_mappings.some((mapping) => mapping.mapping_status === "complete");
    if ((factors.claim_scope_conclusion === "all_elements_mapped") !== hasCompleteClaim
      && ["all_elements_mapped", "missing_elements"].includes(factors.claim_scope_conclusion)) fail("claim_scope_conclusion");
    enumValue("authorization_status", authorizationStatuses);
    if (Object.hasOwn(factors, "claim_change_uncertainty")) enumValue("claim_change_uncertainty", ["low", "medium", "high", "not_applicable", "unknown"]);
    if (Object.hasOwn(factors, "monitoring_trigger")) nullableString("monitoring_trigger");
    return;
  }

  if (["word_mark", "figurative_mark"].includes(candidate.module)) {
    const similarityKey = candidate.module === "word_mark" ? "mark_similarity" : "figurative_similarity";
    allowedKeys(["right_status", "official_record_verified", similarityKey, "goods_services_relatedness", "channels_overlap", "consumer_overlap", "mark_strength", "confusion_likelihood", "authorization_status"]);
    enumValue("right_status", rightStatuses);
    booleanValue("official_record_verified");
    enumValue(similarityKey, gradedSimilarity);
    enumValue("goods_services_relatedness", relatedness);
    booleanOrUnknown("channels_overlap");
    booleanOrUnknown("consumer_overlap");
    enumValue("mark_strength", ["strong", "medium", "weak", "unknown"]);
    enumValue("confusion_likelihood", relatedness);
    enumValue("authorization_status", authorizationStatuses);
    return;
  }

  if (candidate.module === "trade_dress") {
    allowedKeys(["identified_trade_dress_claim", "nonfunctionality", "distinctiveness", "source_identification", "confusion_likelihood", "authorization_status"]);
    if (typeof factors.identified_trade_dress_claim !== "string"
      || factors.identified_trade_dress_claim.trim().length < 8
      || ["unknown", "未知", "待确认"].includes(factors.identified_trade_dress_claim.trim().toLowerCase())) fail("identified_trade_dress_claim");
    for (const key of ["nonfunctionality", "distinctiveness", "source_identification"]) enumValue(key, ["established", "supported", "not_established", "unknown"]);
    enumValue("confusion_likelihood", relatedness);
    enumValue("authorization_status", authorizationStatuses);
    return;
  }

  if (candidate.module === "copyright_creative_ip") {
    allowedKeys(["asset_scope", "protectable_expression", "asset_match", "expression_similarity", "creator_or_earliest_source", "ownership_reliability", "authorization_status", "commercial_use_covered"]);
    enumValue("asset_scope", ["product_sculpture", "listing_image", "packaging", "other", "unknown"]);
    enumValue("protectable_expression", ["established", "likely", "weak", "none", "unknown"]);
    enumValue("asset_match", gradedSimilarity);
    enumValue("expression_similarity", gradedSimilarity);
    nullableString("creator_or_earliest_source");
    enumValue("ownership_reliability", ["high", "medium", "low", "unknown"]);
    enumValue("authorization_status", authorizationStatuses);
    booleanOrUnknown("commercial_use_covered");
    return;
  }

  if (candidate.module === "enforcement_public_signals") {
    allowedKeys(["event_verified", "claimant", "case_or_complaint_id", "subject_match", "procedure_status", "underlying_risk_driver_ids"]);
    booleanValue("event_verified");
    if (!nonBlankString(factors.claimant)) fail("claimant");
    if (!nonBlankString(factors.case_or_complaint_id)) fail("case_or_complaint_id");
    if (typeof candidate.record_number !== "string" || candidate.record_number.length === 0
      || candidate.record_number !== factors.case_or_complaint_id) fail("case_or_complaint_id");
    enumValue("subject_match", ["exact", "strong", "partial", "none", "unknown"]);
    enumValue("procedure_status", ["active_tro", "active_injunction", "active_litigation", "active_complaint", "platform_enforcement", "closed", "dismissed", "unknown"]);
    stringArray("underlying_risk_driver_ids", { nonEmpty: true });
  }
}

function validateCandidate(candidate, index, { allowUnresolved = false } = {}) {
  const prefix = `candidate[${index}]`;
  if (!candidate || typeof candidate !== "object") throw new InputError(`${prefix} must be an object`);
  if (!candidate.candidate_id) throw new InputError(`${prefix}.candidate_id is required`);
  if (!MODULES.includes(candidate.module)) throw new InputError(`${prefix}.module is invalid: ${candidate.module}`);
  if (!RECORD_KINDS.has(candidate.record_kind)) throw new InputError(`${prefix}.record_kind is invalid`);
  if (!LEGAL_MATERIALITIES.has(candidate.legal_materiality)) throw new InputError(`${prefix}.legal_materiality is invalid`);
  if (!AUTHORITY_TIERS.has(candidate.authority_tier)) throw new InputError(`${prefix}.authority_tier is invalid`);
  if (!EVIDENCE_ROLES.has(candidate.evidence_role)) throw new InputError(`${prefix}.evidence_role is invalid`);
  if (!candidate.evidence_cluster_id) throw new InputError(`${prefix}.evidence_cluster_id is required`);
  if (!candidate.independence_group) throw new InputError(`${prefix}.independence_group is required`);
  if (LEGAL_RECORD_KINDS.has(candidate.record_kind)
    && !RISK_RECORD_KINDS[candidate.module].has(candidate.record_kind)) {
    throw new InputError(
      `${prefix} record_kind is incompatible with ${candidate.module}`,
      candidate.legal_materiality === "risk_bearing" ? "RISK_DRIVER_RECORD_KIND_MISMATCH" : "LEGAL_RECORD_KIND_MISMATCH",
    );
  }
  const validRefArray = (value, { nonEmpty = false } = {}) => (
    Array.isArray(value)
    && (!nonEmpty || value.length > 0)
    && value.every((item) => typeof item === "string" && item.length > 0)
    && new Set(value).size === value.length
  );
  if (!validRefArray(candidate.evidence_refs, { nonEmpty: true })) throw new InputError(`${prefix}.evidence_refs is invalid`, "CANDIDATE_EVIDENCE_REFS_INVALID");
  if (!validRefArray(candidate.verification_refs)) throw new InputError(`${prefix}.verification_refs is invalid`, "CANDIDATE_VERIFICATION_REFS_INVALID");
  if (!allowUnresolved && candidate.legal_materiality === "unresolved") {
    throw new InputError(`${prefix} remains unresolved`, "UNRESOLVED_CANDIDATE");
  }
  if (["material", "needs_review"].includes(candidate.legacy_disposition)
    && candidate.legacy_reassessed !== true
    && candidate.legal_materiality !== "unresolved") {
    throw new InputError(`${prefix} legacy relevance must be explicitly reassessed before it can drive v2`, "LEGACY_REASSESSMENT_REQUIRED");
  }
  if (candidate.legacy_disposition === "not_material"
    && candidate.legacy_reassessed !== true
    && candidate.legal_materiality !== "not_material") {
    throw new InputError(`${prefix} legacy exclusion must be explicitly reassessed before reclassification`, "LEGACY_REASSESSMENT_REQUIRED");
  }
  if (candidate.legal_materiality === "risk_bearing") {
    if (candidate.risk_driver_eligible !== true) {
      throw new InputError(`${prefix} risk_bearing requires risk_driver_eligible=true`);
    }
    if (candidate.evidence_role !== "risk_driver") {
      throw new InputError(`${prefix} risk_bearing requires evidence_role=risk_driver`, "RISK_DRIVER_ROLE_MISMATCH");
    }
    if (candidate.target_jurisdiction !== "US" || candidate.right_jurisdiction !== "US") {
      throw new InputError(`${prefix} risk_bearing candidate must be legally applicable in the US`, "RISK_DRIVER_JURISDICTION_MISMATCH");
    }
    if (NON_RIGHT_KINDS.has(candidate.record_kind)) {
      throw new InputError(`${prefix} ${candidate.record_kind} cannot directly drive legal risk`, "NON_RIGHT_RISK_DRIVER");
    }
    if (!RISK_RECORD_KINDS[candidate.module].has(candidate.record_kind)) {
      throw new InputError(`${prefix} record_kind is incompatible with ${candidate.module}`, "RISK_DRIVER_RECORD_KIND_MISMATCH");
    }
    if (array(candidate.evidence_refs).length === 0) {
      throw new InputError(`${prefix} risk_bearing requires evidence_refs`);
    }
    if (!candidate.factors || typeof candidate.factors !== "object") {
      throw new InputError(`${prefix} risk_bearing requires structured factors`);
    }
    const missingFactors = requiredRiskFactors(candidate.module)
      .filter((key) => !Object.hasOwn(candidate.factors, key));
    if (missingFactors.length > 0) {
      throw new InputError(`${prefix} missing required factors: ${missingFactors.join(", ")}`, "MODULE_FACTORS_INCOMPLETE");
    }
    validateRiskFactors(candidate, prefix);
  } else {
    if (candidate.risk_driver_eligible === true) {
      throw new InputError(`${prefix} only risk_bearing may be risk_driver_eligible`);
    }
    if (candidate.evidence_role === "risk_driver") {
      throw new InputError(`${prefix} only risk_bearing may use evidence_role=risk_driver`, "RISK_DRIVER_ROLE_MISMATCH");
    }
    const legallyTestedExclusion = isLegallyTestedExclusionCandidate(candidate);
    if (legallyTestedExclusion) {
      if (!candidate.factors || typeof candidate.factors !== "object") {
        throw new InputError(`${prefix} legal-record exclusion requires structured factors`, "COMPARISON_FACTORS_INCOMPLETE");
      }
      const missingFactors = requiredRiskFactors(candidate.module)
        .filter((key) => !Object.hasOwn(candidate.factors, key));
      if (missingFactors.length > 0) {
        throw new InputError(`${prefix} legal-record exclusion omits factors: ${missingFactors.join(", ")}`, "COMPARISON_FACTORS_INCOMPLETE");
      }
      validateRiskFactors(candidate, prefix);
      const comparisonResult = evaluateCandidate(candidate);
      if (comparisonResult.legal_risk !== "low") {
        throw new InputError(`${prefix} cannot be excluded as ${candidate.legal_materiality} because its structured test is ${comparisonResult.legal_risk}`, "COMPARISON_CLASSIFICATION_UNSUPPORTED");
      }
    }
  }
}

function extractCandidates(input) {
  if (Array.isArray(input?.candidates)) return input.candidates;
  if (Array.isArray(input?.items)) return input.items;
  if (Array.isArray(input?.decisions)) return input.decisions.map((decision) => decision.candidate);
  if (Array.isArray(input?.candidate_review_template?.decisions)) {
    return input.candidate_review_template.decisions.map((decision) => decision.candidate);
  }
  return [];
}

function validateCandidateCollection(input, { allowUnresolved = false } = {}) {
  const candidates = extractCandidates(input);
  const seen = new Set();
  candidates.forEach((candidate, index) => {
    validateCandidate(candidate, index, { allowUnresolved });
    if (seen.has(candidate.candidate_id)) throw new InputError(`duplicate candidate_id: ${candidate.candidate_id}`);
    seen.add(candidate.candidate_id);
  });
  const candidateById = new Map(candidates.map((candidate) => [candidate.candidate_id, candidate]));
  const clusterGroups = new Map();
  for (const candidate of candidates) {
    if (!clusterGroups.has(candidate.evidence_cluster_id)) clusterGroups.set(candidate.evidence_cluster_id, new Set());
    clusterGroups.get(candidate.evidence_cluster_id).add(candidate.independence_group);
  }
  for (const [clusterId, groups] of clusterGroups) {
    if (groups.size > 1) {
      throw new InputError(`evidence cluster ${clusterId} spans multiple independence groups`, "EVIDENCE_CLUSTER_INDEPENDENCE_MISMATCH");
    }
  }
  for (const candidate of candidates) {
    if (!candidate.duplicate_of) continue;
    const target = candidateById.get(candidate.duplicate_of);
    if (!target) throw new InputError(`${candidate.candidate_id}.duplicate_of target does not exist`, "DUPLICATE_TARGET_UNKNOWN");
    if (target.candidate_id === candidate.candidate_id) throw new InputError(`${candidate.candidate_id} cannot duplicate itself`, "DUPLICATE_SELF_REFERENCE");
    if (target.evidence_cluster_id !== candidate.evidence_cluster_id
      || target.independence_group !== candidate.independence_group) {
      throw new InputError(`${candidate.candidate_id}.duplicate_of must stay in the same evidence cluster and independence group`, "DUPLICATE_CLUSTER_MISMATCH");
    }
  }
  const visiting = new Set();
  const visited = new Set();
  function visit(candidateId) {
    if (visited.has(candidateId)) return;
    if (visiting.has(candidateId)) throw new InputError(`duplicate_of cycle detected at ${candidateId}`, "DUPLICATE_REFERENCE_CYCLE");
    visiting.add(candidateId);
    const next = candidateById.get(candidateId)?.duplicate_of;
    if (next) visit(next);
    visiting.delete(candidateId);
    visited.add(candidateId);
  }
  for (const candidate of candidates) visit(candidate.candidate_id);
  return candidates;
}

function validateAssessmentInput(input) {
  if (!input || typeof input !== "object") throw new InputError("assessment input must be an object");
  if (input.schema_version !== SCHEMA_VERSION) throw new InputError(`schema_version must be ${SCHEMA_VERSION}`);
  if (input.ruleset_version !== RULESET_VERSION) throw new InputError(`ruleset_version must be ${RULESET_VERSION}`);
  if (!input.task_id) throw new InputError("task_id is required");
  if (!["draft", "final"].includes(input.assessment_status)) throw new InputError("assessment_status must be draft or final");
  // Finalization may intentionally produce an incomplete result when unresolved
  // candidates remain. The release gate, not parsing, blocks a formal conclusion.
  const candidates = validateCandidateCollection(input, { allowUnresolved: true });
  const modules = array(input.modules);
  if (modules.length !== MODULES.length) throw new InputError(`modules must contain exactly ${MODULES.length} entries`);
  const moduleNames = modules.map((item) => item.module);
  if (new Set(moduleNames).size !== MODULES.length || MODULES.some((module) => !moduleNames.includes(module))) {
    throw new InputError("modules must contain every v2 module exactly once");
  }
  for (const module of modules) {
    if (!["assessable", "partially_assessable", "not_assessable"].includes(module.assessability)) {
      throw new InputError(`invalid assessability for ${module.module}`);
    }
    if (!CONFIDENCE_ORDER.includes(module.confidence)) throw new InputError(`invalid confidence for ${module.module}`);
    if (!Array.isArray(module.candidate_ids)
      || module.candidate_ids.some((item) => typeof item !== "string" || item.length === 0)
      || new Set(module.candidate_ids).size !== module.candidate_ids.length) {
      throw new InputError(`${module.module}.candidate_ids is invalid`, "MODULE_CANDIDATES_INVALID");
    }
    if (typeof module.reasoning !== "string" || module.reasoning.length === 0) throw new InputError(`${module.module}.reasoning is required`, "MODULE_REASONING_REQUIRED");
    if (module.provenance_complete !== undefined && typeof module.provenance_complete !== "boolean") {
      throw new InputError(`${module.module}.provenance_complete must be boolean`, "MODULE_INPUT_INVALID");
    }
    for (const field of ["unresolved_material_facts", "recommended_actions"]) {
      if (module[field] !== undefined && (!Array.isArray(module[field])
        || module[field].some((item) => typeof item !== "string" || item.length === 0)
        || new Set(module[field]).size !== module[field].length)) {
        throw new InputError(`${module.module}.${field} must be a unique string array`, "MODULE_INPUT_INVALID");
      }
    }
  }
  const candidateById = new Map(candidates.map((candidate) => [candidate.candidate_id, candidate]));
  const referencedIds = new Set();
  for (const module of modules) {
    for (const candidateId of array(module.candidate_ids)) {
      const candidate = candidateById.get(candidateId);
      if (!candidate) throw new InputError(`${module.module} references unknown candidate: ${candidateId}`, "CANDIDATE_REFERENCE_UNKNOWN");
      if (candidate.module !== module.module) {
        throw new InputError(`${candidateId} belongs to ${candidate.module}, not ${module.module}`, "CANDIDATE_MODULE_MISMATCH");
      }
      if (referencedIds.has(candidateId)) throw new InputError(`candidate referenced more than once: ${candidateId}`, "CANDIDATE_REFERENCE_DUPLICATE");
      referencedIds.add(candidateId);
    }
  }
  const unreferenced = candidates.filter((candidate) => !referencedIds.has(candidate.candidate_id));
  if (unreferenced.length > 0) {
    throw new InputError(`module candidate coverage is incomplete: ${unreferenced.map((candidate) => candidate.candidate_id).join(", ")}`, "CANDIDATE_MODULE_COVERAGE_MISMATCH");
  }
  if (!input.review || !Array.isArray(input.review.fact_conflicts)) {
    throw new InputError("review.fact_conflicts is required", "REVIEW_INPUT_INVALID");
  }
  const reviewRefs = input.review.review_refs;
  if (reviewRefs !== undefined) {
    if (!Array.isArray(reviewRefs) || reviewRefs.length !== 2
      || reviewRefs[0]?.round !== "first" || reviewRefs[1]?.round !== "second") {
      throw new InputError("review_refs must bind first and second review artifacts", "REVIEW_REFS_INVALID");
    }
    const seenReviewers = new Set();
    const seenSessions = new Set();
    for (const ref of reviewRefs) {
      if (!/^REV-[a-f0-9]{24}$/.test(ref.review_id ?? "")
        || !/^normalized\/reviews\/[A-Za-z0-9][A-Za-z0-9_.-]*\.json$/.test(ref.path ?? "")
        || !/^[a-f0-9]{64}$/.test(ref.digest ?? "")
        || !/^[a-f0-9]{64}$/.test(ref.context_digest ?? "")
        || !/^[a-f0-9]{64}$/.test(ref.evidence_digest ?? "")
        || typeof ref.reviewer_id !== "string" || ref.reviewer_id.length === 0
        || typeof ref.session_id !== "string" || ref.session_id.length === 0) {
        throw new InputError("review reference metadata is invalid", "REVIEW_REFS_INVALID");
      }
      seenReviewers.add(ref.reviewer_id);
      seenSessions.add(ref.session_id);
    }
    if (seenReviewers.size !== 2 || seenSessions.size !== 2
      || reviewRefs[0].context_digest !== reviewRefs[1].context_digest
      || reviewRefs[0].evidence_digest !== reviewRefs[1].evidence_digest) {
      throw new InputError("review references do not prove independent review of one evidence set", "REVIEW_REFS_INVALID");
    }
  }
  const resolutionRef = input.review.resolution_ref;
  if (resolutionRef !== undefined && resolutionRef !== null
    && (!/^RES-[a-f0-9]{24}$/.test(resolutionRef.resolution_id ?? "")
      || !/^normalized\/resolutions\/[A-Za-z0-9][A-Za-z0-9_.-]*\.json$/.test(resolutionRef.path ?? "")
      || !/^[a-f0-9]{64}$/.test(resolutionRef.digest ?? ""))) {
    throw new InputError("resolution reference metadata is invalid", "RESOLUTION_REF_INVALID");
  }
  let resolvedConflictCount = 0;
  for (const conflict of input.review.fact_conflicts) {
    if (typeof conflict.conflict_id !== "string" || conflict.conflict_id.length === 0
      || !Object.hasOwn(conflict, "first_review_value")
      || !Object.hasOwn(conflict, "second_review_value")
      || conflict.rating_material !== true) {
      throw new InputError("rating-factor conflicts must be complete and material", "CONFLICT_INPUT_INVALID");
    }
    if (!["unresolved", "resolved_by_evidence", "resolved_by_human", "resolved_by_lawyer"].includes(conflict.status)) {
      throw new InputError(`conflict ${conflict.conflict_id} has an invalid status`, "CONFLICT_STATUS_INVALID");
    }
    const candidate = candidateById.get(conflict.candidate_id);
    if (!candidate || candidate.module !== conflict.module) {
      throw new InputError(`conflict ${conflict.conflict_id} does not bind a matching candidate`, "CONFLICT_CANDIDATE_MISMATCH");
    }
    try {
      factorValueAtPath(candidate, conflict.fact_path);
    } catch (error) {
      if (error instanceof InputError) {
        throw new InputError(`conflict ${conflict.conflict_id} has an invalid rating fact path`, "CONFLICT_FACT_PATH_INVALID");
      }
      throw error;
    }
    if (!isRatingDecisionPath(candidate.module, conflict.fact_path)) {
      throw new InputError(`conflict ${conflict.conflict_id} does not target a rating decision factor`, "CONFLICT_FACT_PATH_INVALID");
    }
    if (String(conflict.status).startsWith("resolved_by_")) {
      resolvedConflictCount += 1;
      if (!Object.hasOwn(conflict, "resolution_value") || array(conflict.resolution_evidence_refs).length === 0) {
        throw new InputError(`resolved conflict ${conflict.conflict_id} requires a value and evidence`, "CONFLICT_RESOLUTION_EVIDENCE_REQUIRED");
      }
      if (!sameJson(factorValueAtPath(candidate, conflict.fact_path), conflict.resolution_value)) {
        throw new InputError(`resolved conflict ${conflict.conflict_id} does not match the candidate fact`, "CONFLICT_RESOLUTION_VALUE_MISMATCH");
      }
    }
  }
  if (resolvedConflictCount > 0 && (!reviewRefs || !resolutionRef)) {
    throw new InputError("resolved review conflicts require immutable review and resolution references", "CONFLICT_RESOLUTION_ARTIFACT_REQUIRED");
  }
  if (!input.coverage || !CONFIDENCE_ORDER.includes(input.coverage.confidence)) {
    throw new InputError("coverage.confidence is required");
  }
  if (typeof input.coverage.complete !== "boolean" || !Array.isArray(input.coverage.gaps)) {
    throw new InputError("coverage.complete and coverage.gaps are required", "COVERAGE_INPUT_INVALID");
  }
  for (const gap of input.coverage.gaps) {
    if (!gap || !/^[A-Z][A-Z0-9_]{2,100}$/.test(gap.code ?? "")
      || !MODULES.includes(gap.module)
      || typeof gap.detail !== "string" || gap.detail.length === 0
      || typeof gap.blocking !== "boolean") {
      throw new InputError("coverage gaps must contain code, module, detail and blocking", "COVERAGE_GAP_INVALID");
    }
  }
  return { candidates, modules };
}

function discoverySummary(candidates, coverage) {
  const uniqueClusters = new Set(candidates.map((item) => item.evidence_cluster_id)).size;
  const independentGroups = new Set(candidates.map((item) => item.independence_group)).size;
  const riskBearing = new Set(candidates
    .filter((item) => item.legal_materiality === "risk_bearing" && item.risk_driver_eligible === true)
    .map((item) => `${item.module}:${item.evidence_cluster_id}`)).size;
  const contextual = candidates.filter((item) => (
    ["provenance_lead", "comparison_only"].includes(item.legal_materiality)
    || isLegallyTestedExclusionCandidate(item)
  )).length;
  const provenance = candidates.filter((item) => item.legal_materiality === "provenance_lead").length;
  const unresolved = candidates.filter((item) => item.legal_materiality === "unresolved").length;
  let status = "no_lead";
  if (coverage?.discovery_blocked || coverage?.complete === false) status = "blocked";
  else if (unresolved > 0 || riskBearing > 0 || provenance > 0) status = "review_required";
  else if (contextual > 0) status = "leads_found";
  return {
    status,
    raw_candidate_count: candidates.length,
    unique_evidence_cluster_count: uniqueClusters,
    independent_evidence_group_count: independentGroups,
    risk_driver_count: riskBearing,
    contextual_lead_count: contextual,
    unresolved_count: unresolved,
  };
}

function evaluateAssessment(input) {
  const { candidates, modules } = validateAssessmentInput(input);
  const evaluatedAt = now();
  const reviewArtifactRefs = {
    ...(input.review.review_refs ? { review_refs: input.review.review_refs } : {}),
    ...(Object.hasOwn(input.review, "resolution_ref") ? { resolution_ref: input.review.resolution_ref } : {}),
  };
  const discovery = discoverySummary(candidates, input.coverage);
  const draftBlockingGaps = array(input.coverage.gaps).filter((gap) => gap.blocking !== false);
  const draftCoverageConfidence = bool(input.coverage.complete) && draftBlockingGaps.length === 0
    ? (array(input.coverage.gaps).length === 0 ? input.coverage.confidence : minConfidence(input.coverage.confidence, "medium"))
    : "low";
  const unresolvedConflicts = [
    ...array(input.review?.fact_conflicts).filter((conflict) => conflict.status === "unresolved"),
    ...duplicateRatingFactConflicts(candidates),
  ].filter((conflict, index, all) => all.findIndex((item) => item.conflict_id === conflict.conflict_id) === index);
  if (unresolvedConflicts.length > 0) discovery.status = "blocked";

  if (input.assessment_status === "draft") {
    const draftModules = modules.map((module) => ({
      module: module.module,
      assessability: "not_assessable",
      legal_risk: "not_assessable",
      risk_confidence: "low",
      risk_driver_candidate_ids: [],
      basis_codes: ["ASSESSMENT_NOT_FINALIZED"],
      reasoning: module.reasoning ?? "正式评估尚未完成。",
    }));
    return {
      schema_version: SCHEMA_VERSION,
      ruleset_version: RULESET_VERSION,
      task_id: input.task_id,
      assessment_status: "draft",
      discovery_summary: discovery,
      candidate_summaries: candidates.map(candidateSummary),
      modules: draftModules,
      ...reviewArtifactRefs,
      overall: {
        discovery_status: discovery.status,
        legal_risk: "not_assessable",
        risk_confidence: "low",
        coverage_confidence: draftCoverageConfidence,
        operational_action: unresolvedConflicts.length > 0 ? "escalate_legal" : "hold_for_evidence",
        formal_conclusion_allowed: false,
        risk_driver_modules: [],
        basis_codes: ["ASSESSMENT_NOT_FINALIZED"],
      },
      constraints: {
        formal_conclusion_allowed: false,
        human_resolution_required: unresolvedConflicts.length > 0,
      },
      decision_trace: {
        evaluated_at: evaluatedAt,
        candidate_evaluations: [],
        ignored_duplicate_candidate_ids: [],
        unresolved_fact_conflicts: unresolvedConflicts,
        reason_codes: [
          "ASSESSMENT_NOT_FINALIZED",
          ...(unresolvedConflicts.length > 0 ? ["RATING_FACT_CONFLICT", "HUMAN_RESOLUTION_REQUIRED"] : []),
          "FORMAL_CONCLUSION_BLOCKED",
        ],
      },
    };
  }

  const driverCandidates = candidates.filter((candidate) => (
    candidate.legal_materiality === "risk_bearing" && candidate.risk_driver_eligible === true
  ));
  const contextualCandidates = candidates.filter((candidate) => (
    (["comparison_only", "provenance_lead", "mitigating"].includes(candidate.legal_materiality)
      || isLegallyTestedExclusionCandidate(candidate))
    && candidate.factors && Object.keys(candidate.factors).length > 0
  ));
  const clusterWinners = new Map();
  const ignoredDuplicates = [];
  for (const candidate of driverCandidates) {
    const result = evaluateCandidate(candidate);
    const key = `${candidate.module}:${candidate.evidence_cluster_id}`;
    const existing = clusterWinners.get(key);
    const proposed = { candidate, result };
    if (!existing || compareCandidateEntries(proposed, existing) > 0) {
      if (existing) ignoredDuplicates.push(existing.candidate.candidate_id);
      clusterWinners.set(key, proposed);
    } else {
      ignoredDuplicates.push(candidate.candidate_id);
    }
  }
  const evaluations = [...clusterWinners.values()].map((entry) => entry.result);
  const contextualWinners = new Map();
  for (const candidate of contextualCandidates) {
    const result = evaluateCandidate(candidate);
    const key = `${candidate.module}:${candidate.evidence_cluster_id}`;
    const existing = contextualWinners.get(key);
    const proposed = { candidate, result };
    if (!existing || compareCandidateEntries(proposed, existing) > 0) {
      if (existing) ignoredDuplicates.push(existing.candidate.candidate_id);
      contextualWinners.set(key, proposed);
    } else ignoredDuplicates.push(candidate.candidate_id);
  }
  const contextualEvaluations = [...contextualWinners.values()].map((entry) => entry.result);
  const coverageGaps = array(input.coverage.gaps);
  const driverCandidateById = new Map(driverCandidates.map((candidate) => [candidate.candidate_id, candidate]));
  for (const evaluation of evaluations) {
    if (evaluation.module !== "enforcement_public_signals" || evaluation.legal_risk !== "critical") continue;
    const enforcementCandidate = driverCandidateById.get(evaluation.candidate_id);
    const underlyingIds = new Set(array(factor(enforcementCandidate, "underlying_risk_driver_ids", [])));
    const underlyingClusterKeys = new Set([...underlyingIds].map((candidateId) => {
      const candidate = driverCandidateById.get(candidateId);
      return candidate && candidate.module !== "enforcement_public_signals"
        ? `${candidate.module}:${candidate.evidence_cluster_id}`
        : null;
    }).filter(Boolean));
    const linkedHigh = evaluations.some((other) => (
      other.module !== "enforcement_public_signals"
      && other.legal_risk === "high"
      && underlyingClusterKeys.has(`${other.module}:${driverCandidateById.get(other.candidate_id)?.evidence_cluster_id}`)
      && other.independence_group === evaluation.independence_group
    ));
    if (!linkedHigh) {
      evaluation.legal_risk = "medium";
      evaluation.risk_confidence = "low";
      evaluation.basis_codes.push("CRITICAL_HIGH_BASE_NOT_MET", "ENFORCEMENT_UNDERLYING_DRIVER_LINK_INVALID");
    }
  }

  const evaluatedModules = modules.map((moduleInput) => {
    const moduleConflicts = unresolvedConflicts.filter((conflict) => conflict.module === moduleInput.module);
    const unresolvedMaterialFacts = array(moduleInput.unresolved_material_facts);
    if (moduleInput.assessability === "not_assessable" || moduleConflicts.length > 0 || unresolvedMaterialFacts.length > 0) {
      return {
        module: moduleInput.module,
        assessability: "not_assessable",
        legal_risk: "not_assessable",
        risk_confidence: "low",
        risk_driver_candidate_ids: [],
        basis_codes: moduleConflicts.length > 0
          ? ["UNRESOLVED_RATING_FACT_CONFLICT"]
          : (unresolvedMaterialFacts.length > 0 ? ["UNRESOLVED_MATERIAL_FACTS"] : ["MODULE_NOT_ASSESSABLE"]),
        unresolved_material_facts: unresolvedMaterialFacts,
        reasoning: moduleInput.reasoning ?? "证据不足，模块暂不可评估。",
      };
    }
    const moduleEvaluations = evaluations.filter((item) => item.module === moduleInput.module);
    const unevaluatedDrivers = moduleEvaluations.filter((item) => item.legal_risk === "not_assessable");
    if (unevaluatedDrivers.length > 0) {
      return {
        module: moduleInput.module,
        assessability: "not_assessable",
        legal_risk: "not_assessable",
        risk_confidence: "low",
        risk_driver_candidate_ids: unevaluatedDrivers.map((item) => item.candidate_id),
        basis_codes: [...new Set(unevaluatedDrivers.flatMap((item) => item.basis_codes))],
        unresolved_material_facts: array(moduleInput.unresolved_material_facts),
        reasoning: moduleInput.reasoning ?? "存在尚未完成法律测试的风险驱动候选。",
        recommended_actions: array(moduleInput.recommended_actions),
      };
    }
    let legalRisk;
    let riskConfidence;
    let drivers = [];
    let basisCodes = [];
    if (moduleEvaluations.length === 0) {
      const moduleContextualEvaluations = contextualEvaluations.filter((item) => item.module === moduleInput.module);
      legalRisk = moduleContextualEvaluations.length > 0
        ? "low"
        : (bool(moduleInput.provenance_complete)
          && bool(input.coverage.complete)
          && moduleInput.confidence === "high"
          ? "very_low"
          : "low");
      riskConfidence = moduleInput.assessability === "partially_assessable"
        ? "low"
        : minConfidence(moduleInput.confidence, ...moduleContextualEvaluations.map((item) => item.risk_confidence));
      const contextualCodes = moduleContextualEvaluations.flatMap((item) => item.basis_codes);
      const unresolvedCopyrightProvenance = moduleInput.module === "copyright_creative_ip"
        && !bool(moduleInput.provenance_complete)
        && candidates.some((candidate) => (
          candidate.module === moduleInput.module
          && candidate.legal_materiality === "provenance_lead"
        ));
      if (unresolvedCopyrightProvenance) contextualCodes.push("COPYRIGHT_PROVENANCE_UNRESOLVED");
      basisCodes = contextualCodes.length > 0
        ? [...new Set(contextualCodes)]
        : [legalRisk === "very_low" ? "NO_RISK_DRIVER_AND_PROVENANCE_COMPLETE" : "NO_SUBSTANTIATED_RISK_DRIVER"];
    } else {
      legalRisk = maxRisk(...moduleEvaluations.map((item) => item.legal_risk));
      const top = moduleEvaluations.filter((item) => item.legal_risk === legalRisk);
      drivers = top.map((item) => item.candidate_id);
      riskConfidence = minConfidence(moduleInput.confidence, ...top.map((item) => item.risk_confidence));
      basisCodes = [...new Set(top.flatMap((item) => item.basis_codes))];
      if (moduleInput.assessability === "partially_assessable") riskConfidence = "low";
    }
    const applicableGaps = coverageGaps.filter((gap) => !gap.module || gap.module === moduleInput.module);
    if (applicableGaps.length > 0) {
      const confidenceCap = applicableGaps.some((gap) => gap.blocking !== false) ? "low" : "medium";
      riskConfidence = minConfidence(riskConfidence, confidenceCap);
      basisCodes = [...new Set([...basisCodes, ...applicableGaps.map((gap) => gap.code).filter(Boolean), "CONFIDENCE_CAPPED"])];
    }
    return {
      module: moduleInput.module,
      assessability: moduleInput.assessability,
      legal_risk: legalRisk,
      risk_confidence: riskConfidence,
      risk_driver_candidate_ids: drivers,
      basis_codes: basisCodes,
      unresolved_material_facts: array(moduleInput.unresolved_material_facts),
      reasoning: moduleInput.reasoning ?? "",
      recommended_actions: array(moduleInput.recommended_actions),
    };
  });

  const unresolvedModule = evaluatedModules.some((module) => module.legal_risk === "not_assessable");
  if (unresolvedModule) discovery.status = "blocked";
  const assessedRisks = evaluatedModules.map((module) => module.legal_risk).filter((risk) => RISK_ORDER.includes(risk));
  let overallRisk = maxRisk(...assessedRisks);
  const criticalEnforcementGroups = new Set(evaluations
    .filter((evaluation) => evaluation.module === "enforcement_public_signals" && evaluation.legal_risk === "critical")
    .map((evaluation) => evaluation.independence_group));
  const substantiveHighBasis = evaluations.some((evaluation) => (
    evaluation.module !== "enforcement_public_signals"
    && evaluation.legal_risk === "high"
    && criticalEnforcementGroups.has(evaluation.independence_group)
  ));
  const criticalHighBaseMissing = overallRisk === "critical" && !substantiveHighBasis;
  if (criticalHighBaseMissing) overallRisk = "high";
  const blockingGaps = coverageGaps.filter((gap) => gap.blocking !== false);
  const effectiveCoverageConfidence = coverageGaps.length === 0
    ? input.coverage.confidence
    : minConfidence(input.coverage.confidence, blockingGaps.length > 0 ? "low" : "medium");
  const coverageComplete = bool(input.coverage.complete) && blockingGaps.length === 0;
  if (unresolvedConflicts.length > 0
    || assessedRisks.length === 0
    || (!coverageComplete && ["very_low", "low"].includes(overallRisk))) {
    overallRisk = "not_assessable";
  }
  const sameRiskModules = RISK_ORDER.includes(overallRisk)
    ? evaluatedModules.filter((module) => (
      module.legal_risk === overallRisk
      || (criticalHighBaseMissing && module.module === "enforcement_public_signals" && module.legal_risk === "critical")
    ))
    : [];
  const riskDrivenTopModules = sameRiskModules.filter((module) => module.risk_driver_candidate_ids.length > 0);
  const topModules = riskDrivenTopModules.length > 0 ? riskDrivenTopModules : sameRiskModules;
  const overallConfidence = topModules.length > 0
    ? minConfidence(...topModules.map((module) => module.risk_confidence))
    : "low";
  const partiallyAssessable = evaluatedModules.some((module) => module.assessability === "partially_assessable");
  let action;
  if (unresolvedConflicts.length > 0) action = "escalate_legal";
  else if (discovery.unresolved_count > 0) action = "hold_for_evidence";
  else if (evaluations.some((evaluation) => (
    evaluation.module === "enforcement_public_signals"
    && evaluation.basis_codes.includes("VERIFIED_ENFORCEMENT_EVENT")
  ))) action = "escalate_legal";
  else if (["high", "critical"].includes(overallRisk)) action = "escalate_legal";
  else if (partiallyAssessable) action = "hold_for_evidence";
  else if (overallRisk === "not_assessable" || !coverageComplete || unresolvedModule) action = "hold_for_evidence";
  else if (overallRisk === "medium") {
    const mediumDrivers = driverCandidates.filter((candidate) => topModules.some((module) => module.risk_driver_candidate_ids.includes(candidate.candidate_id)));
    const unresolvedAuthorization = mediumDrivers.some((candidate) => (
      (Object.hasOwn(candidate.factors, "authorization_status")
        && ["unknown", "unresolved"].includes(candidate.factors.authorization_status))
      || (candidate.module === "copyright_creative_ip"
        && ["unknown", "low"].includes(candidate.factors.ownership_reliability))
    ));
    const provenanceUnresolved = topModules.some((module) => module.basis_codes.includes("COPYRIGHT_PROVENANCE_UNRESOLVED"));
    const ratingFactUnresolved = topModules.some((module) => module.basis_codes.some((code) => (
      /(?:UNRESOLVED|UNKNOWN|NOT_ASSESSED|INSUFFICIENT|INCOMPLETE)/.test(code)
    )));
    action = unresolvedAuthorization || provenanceUnresolved || ratingFactUnresolved ? "hold_for_evidence" : "proceed_with_conditions";
  } else if (evaluatedModules.some((module) => module.basis_codes.includes("COPYRIGHT_PROVENANCE_UNRESOLVED"))) {
    action = "hold_for_evidence";
  } else if (["very_low", "low"].includes(overallRisk)
    && overallConfidence === "high"
    && effectiveCoverageConfidence === "high"
    && coverageComplete
    && discovery.status === "no_lead") action = "proceed";
  else action = "proceed_with_conditions";

  const formalAllowed = coverageComplete
    && !unresolvedModule
    && unresolvedConflicts.length === 0
    && discovery.unresolved_count === 0;
  const overallBasis = [];
  if (!coverageComplete) overallBasis.push("COVERAGE_INCOMPLETE");
  if (unresolvedModule) overallBasis.push("MODULE_NOT_ASSESSABLE");
  if (unresolvedConflicts.length > 0) overallBasis.push("UNRESOLVED_RATING_FACT_CONFLICT");
  if (criticalHighBaseMissing) overallBasis.push("CRITICAL_HIGH_BASE_NOT_MET");
  if (formalAllowed) overallBasis.push("FORMAL_ASSESSMENT_COMPLETE");
  const traceReasonCodes = [
    ...evaluations.flatMap((item) => item.basis_codes),
    ...contextualEvaluations.flatMap((item) => item.basis_codes),
    ...overallBasis,
    ...array(input.coverage.gaps).map((gap) => gap.code).filter(Boolean),
  ];
  if (ignoredDuplicates.length > 0) traceReasonCodes.push("DUPLICATE_EVIDENCE_COLLAPSED");
  if (!coverageComplete) traceReasonCodes.push("CONFIDENCE_CAPPED", "FORMAL_CONCLUSION_BLOCKED");
  if (unresolvedModule && !traceReasonCodes.includes("FORMAL_CONCLUSION_BLOCKED")) traceReasonCodes.push("FORMAL_CONCLUSION_BLOCKED");
  if (unresolvedConflicts.length > 0) traceReasonCodes.push("RATING_FACT_CONFLICT", "HUMAN_RESOLUTION_REQUIRED", "FORMAL_CONCLUSION_BLOCKED");
  if (discovery.unresolved_count > 0 && !traceReasonCodes.includes("FORMAL_CONCLUSION_BLOCKED")) traceReasonCodes.push("FORMAL_CONCLUSION_BLOCKED");
  const publicRisk = formalAllowed ? overallRisk : "not_assessable";
  const publicConfidence = formalAllowed ? overallConfidence : "low";

  return {
    schema_version: SCHEMA_VERSION,
    ruleset_version: RULESET_VERSION,
    task_id: input.task_id,
    assessment_status: formalAllowed ? "final" : "incomplete",
    discovery_summary: discovery,
    candidate_summaries: candidates.map(candidateSummary),
    modules: evaluatedModules,
    ...reviewArtifactRefs,
    overall: {
      discovery_status: discovery.status,
      legal_risk: publicRisk,
      working_legal_risk: overallRisk,
      risk_confidence: publicConfidence,
      coverage_confidence: coverageComplete ? effectiveCoverageConfidence : "low",
      operational_action: action,
      formal_conclusion_allowed: formalAllowed,
      risk_driver_modules: topModules
        .filter((module) => module.risk_driver_candidate_ids.length > 0)
        .map((module) => module.module),
      basis_codes: overallBasis,
    },
    constraints: {
      formal_conclusion_allowed: formalAllowed,
      human_resolution_required: unresolvedConflicts.length > 0,
    },
    decision_trace: {
      evaluated_at: evaluatedAt,
      candidate_evaluations: [...evaluations, ...contextualEvaluations],
      ignored_duplicate_candidate_ids: ignoredDuplicates,
      unresolved_fact_conflicts: unresolvedConflicts,
      aggregation: "highest substantiated module risk; no compound escalation",
      reason_codes: [...new Set(traceReasonCodes)],
    },
  };
}

function mapLegacyModule(module) {
  if (module === "figurative_trade_dress") return "trade_dress";
  if (MODULES.includes(module)) return module;
  throw new InputError(`unsupported legacy module: ${module}`, "MODULE_UNSUPPORTED");
}

function legacyDisposition(candidate) {
  return candidate?.disposition?.value ?? candidate?.disposition ?? "needs_review";
}

function inferRecordKind(candidate) {
  if (candidate.module === "pending_patent") return "application";
  if (candidate.module === "enforcement_public_signals") return "enforcement_event";
  if (candidate.record_number) return "right_record";
  if (candidate.module === "copyright_creative_ip") return "creative_source";
  return "comparison_material";
}

function normalizeJurisdiction(value) {
  const normalized = String(value ?? "").toUpperCase();
  return /^[A-Z][A-Z0-9-]{1,15}$/.test(normalized) ? normalized : null;
}

function migrateLegacyCandidate(candidate) {
  const legacy = legacyDisposition(candidate);
  const legalMateriality = legacy === "not_material" ? "not_material" : "unresolved";
  const clusterSeed = candidate.record_number
    || candidate.candidate_key?.split(":").at(-1)
    || candidate.candidate_id;
  return {
    candidate_id: candidate.candidate_id,
    module: mapLegacyModule(candidate.module),
    record_kind: inferRecordKind(candidate),
    legal_materiality: legalMateriality,
    evidence_role: legalMateriality === "not_material" ? "context" : "provenance",
    authority_tier: "unknown",
    target_jurisdiction: "US",
    source_jurisdiction: normalizeJurisdiction(candidate.jurisdiction),
    right_jurisdiction: candidate.record_number ? normalizeJurisdiction(candidate.jurisdiction) : null,
    record_number: candidate.record_number ?? null,
    title: candidate.title ?? null,
    owner: candidate.owner ?? null,
    source_locator: candidate.source_locator ?? null,
    published_at: null,
    first_seen_at: null,
    evidence_cluster_id: `CL-${sha256(String(clusterSeed)).slice(0, 16)}`,
    independence_group: `IG-${sha256(String(clusterSeed)).slice(0, 16)}`,
    duplicate_of: null,
    risk_driver_eligible: false,
    evidence_refs: array(candidate.evidence_refs),
    verification_refs: [],
    factors: {},
    legacy_module: candidate.module ?? null,
    legacy_disposition: legacy,
    legacy_reassessed: false,
  };
}

function migrateCandidates(taskDir) {
  const ledgerPath = join(taskDir, "05_evidence_ledger.json");
  const ledger = readJson(ledgerPath, "legacy evidence ledger");
  const legacyCandidates = array(ledger.candidates);
  const items = legacyCandidates.map(migrateLegacyCandidate);
  const decisions = items.map((candidate, index) => ({
    candidate,
    rationale: candidate.legal_materiality === "not_material"
      ? "Legacy not_material retained; reviewer must confirm the v2 structured exclusion."
      : "REVIEW_REQUIRED: legacy relevance labels cannot drive v2 legal risk.",
    workspace_context_index: index,
  }));
  const output = {
    schema_version: SCHEMA_VERSION,
    ruleset_version: RULESET_VERSION,
    task_id: ledger.task_id,
    migrated_from: {
      schema_version: ledger.schema_version ?? "0.1",
      evidence_digest: ledger.digest ?? null,
      rule: "legacy material and needs_review become unresolved; not_material remains not_material",
    },
    generated_at: now(),
    candidate_count: items.length,
    candidate_review_template: {
      schema_version: SCHEMA_VERSION,
      ruleset_version: RULESET_VERSION,
      task_id: ledger.task_id,
      evidence_digest: ledger.digest ?? "",
      decided_by: null,
      decisions: decisions.map(({ workspace_context_index: _index, ...decision }) => decision),
    },
    workspace_context: legacyCandidates.map((candidate, index) => ({
      index,
      candidate_id: candidate.candidate_id,
      legacy_module: candidate.module,
      title: candidate.title ?? "",
      owner: candidate.owner ?? null,
      record_number: candidate.record_number ?? null,
      deterministic_triggers: array(candidate?.disposition?.deterministic_triggers),
      exclusion_codes: array(candidate?.disposition?.exclusion_codes),
      legacy_rationale: candidate?.disposition?.rationale ?? "",
      migration_note: candidate.module === "figurative_trade_dress"
        ? "Defaulted to trade_dress; reclassify to figurative_mark when the evidence is a source-identifying graphic mark."
        : null,
    })),
  };
  const outputPath = join(taskDir, "v2", "candidate-review-workspace.json");
  writeJson(outputPath, output);
  const legacyReportMetadataPath = join(taskDir, "v2", "legacy-report-metadata.json");
  const legacyReportRelativePath = [
    "report/ipr-risk-screening-report.html",
    "report-draft/ipr-risk-screening-report.html",
  ].find((relativePath) => existsSync(join(taskDir, relativePath))) ?? null;
  const legacyWrapperRelativePath = "v2/legacy-discovery-report.html";
  const legacyWrapperPath = join(taskDir, legacyWrapperRelativePath);
  const legacyLink = legacyReportRelativePath
    ? `<p><a href="../${escapeHtml(legacyReportRelativePath)}">仅作为历史发现记录打开原报告</a></p>`
    : "<p>未在任务目录中找到旧版 HTML；请仅使用迁移工作区继续 v2 复评。</p>";
  writeFileSync(legacyWrapperPath, `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>旧版发现报告｜评估尚未完成</title>
<style>body{margin:0;background:#f4f6f8;color:#17202a;font:16px/1.65 system-ui,-apple-system,sans-serif}.wrap{max-width:760px;margin:8vh auto;padding:36px;background:#fff;border:1px solid #d7dde4;border-radius:18px;box-shadow:0 16px 50px #20304014}.label{display:inline-block;padding:5px 10px;border-radius:999px;background:#fff4d6;color:#7a5200;font-weight:700}.status{font-size:34px;margin:18px 0 8px}.note{padding:18px;border-left:5px solid #e2a100;background:#fffaf0}a{color:#075e9e}.meta{color:#64717d;font-size:14px}</style>
</head><body><main class="wrap"><span class="label">legacy discovery report · 旧版发现报告</span>
<h1 class="status">评估尚未完成</h1><p class="note">旧报告中的高低风险字样来自发现层候选映射，不是 v2 法律风险结论。旧版 <code>material</code> 已迁移为 <code>unresolved</code>，在完成结构化复评前不得作为风险驱动。</p>
${legacyLink}<p class="meta">任务：${escapeHtml(ledger.task_id)} · 法律风险：无法评估 · 正式结论：不允许</p></main></body></html>`);
  writeJson(legacyReportMetadataPath, {
    schema_version: SCHEMA_VERSION,
    ruleset_version: RULESET_VERSION,
    task_id: ledger.task_id,
    report_mode: "legacy",
    label: "legacy discovery report",
    legal_risk: "not_assessable",
    formal_conclusion_allowed: false,
    source_evidence_digest: ledger.digest ?? null,
    wrapper_path: legacyWrapperRelativePath,
    source_report_path: legacyReportRelativePath,
    migration_policy: "legacy material and needs_review remain unresolved until explicit v2 reassessment",
  });
  const sourceManifestReady = [
    "02_product_facts.json",
    "04_query_plan.json",
    "05_evidence_ledger.json",
    "checkpoints/coverage.json",
  ].every((relativePath) => existsSync(join(taskDir, relativePath)));
  let sourceManifest = null;
  if (sourceManifestReady) {
    const existingManifestPath = join(taskDir, SOURCE_MANIFEST_RELATIVE_PATH);
    const existingManifest = existsSync(existingManifestPath)
      ? readJson(existingManifestPath, "existing v2 frozen-source manifest")
      : null;
    sourceManifest = writeSourceManifest(
      taskDir,
      ledger.task_id,
      readJson(join(taskDir, "02_product_facts.json"), "product facts"),
      ledger,
      existingManifest ? {
        revision: existingManifest.revision + 1,
        parentDigest: existingManifest.digest,
      } : {},
    );
  }
  return {
    output_path: outputPath,
    legacy_report_metadata_path: legacyReportMetadataPath,
    legacy_report_wrapper_path: legacyWrapperPath,
    source_manifest_path: sourceManifest ? join(taskDir, SOURCE_MANIFEST_RELATIVE_PATH) : null,
    candidate_count: items.length,
    unresolved_total: items.filter((item) => item.legal_materiality === "unresolved").length,
  };
}

function validateCandidatesFile(inputPath) {
  const review = readJson(inputPath, "v2 candidate review");
  const candidates = validateCandidateCollection(review);
  const workspacePath = join(dirname(inputPath), "candidate-review-workspace.json");
  validateCandidateCoverageAgainstWorkspace(candidates, workspacePath);
  return {
    status: "valid",
    reason_code: "V2_CANDIDATES_VALID",
    candidate_total: candidates.length,
    unique_cluster_total: new Set(candidates.map((item) => item.evidence_cluster_id)).size,
    risk_bearing_total: candidates.filter((item) => item.legal_materiality === "risk_bearing").length,
  };
}

function validateCandidateCoverageAgainstWorkspace(candidates, workspacePath) {
  if (existsSync(workspacePath)) {
    const workspace = readJson(workspacePath, "candidate workspace");
    const expectedCandidates = extractCandidates(workspace);
    const expectedById = new Map(expectedCandidates.map((item) => [item.candidate_id, item]));
    const expected = new Set(expectedById.keys());
    const actual = new Set(candidates.map((item) => item.candidate_id));
    const missing = [...expected].filter((id) => !actual.has(id));
    const derived = candidates.filter((candidate) => !expected.has(candidate.candidate_id));
    const invalidDerived = derived.filter((candidate) => !candidate.duplicate_of || !expected.has(candidate.duplicate_of));
    if (missing.length > 0 || invalidDerived.length > 0) {
      throw new InputError("candidate review does not exactly cover the migrated workspace", "CANDIDATE_COVERAGE_MISMATCH");
    }
    for (const candidate of candidates.filter((item) => expected.has(item.candidate_id))) {
      const migrated = expectedById.get(candidate.candidate_id);
      if (migrated.legacy_disposition !== undefined) {
        if (candidate.legacy_disposition !== migrated.legacy_disposition
          || typeof candidate.legacy_reassessed !== "boolean") {
          throw new InputError(
            `${candidate.candidate_id} drops its legacy disposition or reassessment state`,
            "LEGACY_REASSESSMENT_REQUIRED",
          );
        }
        if (candidate.legacy_reassessed !== true
          && candidate.legal_materiality !== migrated.legal_materiality) {
          throw new InputError(
            `${candidate.candidate_id} changes its migrated classification without explicit reassessment`,
            "LEGACY_REASSESSMENT_REQUIRED",
          );
        }
      }
    }
  }
}

function prepareAssessment(taskDir, candidateReviewPath) {
  const review = readJson(candidateReviewPath, "v2 candidate review");
  const candidates = validateCandidateCollection(review);
  validateCandidateCoverageAgainstWorkspace(candidates, join(taskDir, "v2", "candidate-review-workspace.json"));
  const coveragePath = join(taskDir, "checkpoints", "coverage.json");
  const coverageCheckpoint = existsSync(coveragePath) ? readJson(coveragePath, "coverage checkpoint") : {};
  const incompleteRows = array(coverageCheckpoint.rows).filter((row) => row?.required === true && row.coverage_status !== "complete");
  const gapModules = (module) => module === "figurative_trade_dress" ? ["figurative_mark", "trade_dress"] : [module];
  const gaps = incompleteRows.flatMap((row) => gapModules(row.module).map((module) => ({
    code: String(row.reason_code || "QUERY_INCOMPLETE").toUpperCase().replace(/[^A-Z0-9_]/g, "_").slice(0, 100),
    module,
    detail: `Required discovery query ${row.query_id} is ${row.coverage_status}.`,
    blocking: true,
  })));
  const complete = coverageCheckpoint.status === "complete"
    && coverageCheckpoint.assessment_ready === true
    && Number.isInteger(coverageCheckpoint.required_total)
    && coverageCheckpoint.completed_total === coverageCheckpoint.required_total
    && gaps.length === 0
    && array(coverageCheckpoint.gap_query_ids).length === 0;
  if (!complete && gaps.length === 0) {
    gaps.push({ code: "COVERAGE_CHECKPOINT_INCOMPLETE", module: "appearance_design", detail: "Discovery coverage checkpoint is missing or not assessment-ready.", blocking: true });
  }
  const input = {
    schema_version: SCHEMA_VERSION,
    ruleset_version: RULESET_VERSION,
    task_id: review.task_id,
    assessment_status: complete && gaps.length === 0 ? "final" : "draft",
    coverage: {
      complete: complete && gaps.length === 0,
      confidence: complete && gaps.length === 0 ? "high" : "low",
      gaps,
    },
    candidates,
    modules: MODULES.map((module) => ({
      module,
      assessability: "not_assessable",
      confidence: "low",
      candidate_ids: candidates.filter((candidate) => candidate.module === module).map((candidate) => candidate.candidate_id),
      provenance_complete: false,
      unresolved_material_facts: [],
      reasoning: "REVIEW_REQUIRED",
      recommended_actions: [],
    })),
    review: { fact_conflicts: [] },
  };
  const outputPath = join(taskDir, "v2", "assessment-input.json");
  writeJson(outputPath, input);
  return { output_path: outputPath, assessment_status: input.assessment_status, module_total: MODULES.length };
}

function validRefList(value, { nonEmpty = false } = {}) {
  return Array.isArray(value)
    && (!nonEmpty || value.length > 0)
    && value.every((item) => nonBlankString(item))
    && new Set(value).size === value.length;
}

function validateReviewArtifact(review, expectedRound, expectedContextDigest, expectedEvidenceDigest) {
  if (!review || review.schema_version !== SCHEMA_VERSION || review.ruleset_version !== RULESET_VERSION) {
    throw new InputError(`${expectedRound} review uses an unsupported contract or ruleset`, "REVIEW_VERSION_MISMATCH");
  }
  if (review.round !== expectedRound) throw new InputError(`${expectedRound} review has the wrong round`, "REVIEW_ROUND_MISMATCH");
  if (!/^REV-[a-f0-9]{24}$/.test(review.review_id ?? "")
    || !/^[a-f0-9]{64}$/.test(review.digest ?? "")
    || review.digest !== immutableArtifactDigest(review)) {
    throw new InputError(`${expectedRound} review is not an immutable digest-bound artifact`, "REVIEW_DIGEST_MISMATCH");
  }
  if (review.context_digest !== expectedContextDigest || review.evidence_digest !== expectedEvidenceDigest) {
    throw new InputError(`${expectedRound} review is not bound to this assessment input`, "REVIEW_CONTEXT_MISMATCH");
  }
  if (!review.reviewer || !["agent", "human", "reviewer"].includes(review.reviewer.type)
    || typeof review.reviewer.id !== "string" || review.reviewer.id.length === 0
    || typeof review.reviewer.session_id !== "string" || review.reviewer.session_id.length === 0
    || !validRefList(review.declared_input_refs, { nonEmpty: true })
    || typeof review.submitted_at !== "string" || Number.isNaN(Date.parse(review.submitted_at))
    || !Array.isArray(review.fact_conflicts)) {
    throw new InputError(`${expectedRound} review metadata is incomplete`, "REVIEW_METADATA_INVALID");
  }
  if (!review.isolation || !["declared_only", "runtime_enforced"].includes(review.isolation.mode)
    || review.isolation.prior_review_read !== false
    || (review.isolation.mode === "runtime_enforced"
      && (typeof review.isolation.proof_id !== "string" || review.isolation.proof_id.length === 0))) {
    throw new InputError(`${expectedRound} review isolation is not supported by its declaration`, "REVIEW_ISOLATION_INVALID");
  }
}

function validateResolutionArtifact(resolution, taskId, expectedContextDigest, expectedEvidenceDigest) {
  if (!resolution || resolution.task_id !== taskId
    || resolution.schema_version !== SCHEMA_VERSION
    || resolution.ruleset_version !== RULESET_VERSION
    || !/^RES-[a-f0-9]{24}$/.test(resolution.resolution_id ?? "")
    || !/^[a-f0-9]{64}$/.test(resolution.digest ?? "")
    || resolution.digest !== immutableArtifactDigest(resolution)
    || resolution.context_digest !== expectedContextDigest
    || resolution.evidence_digest !== expectedEvidenceDigest) {
    throw new InputError("resolution is not bound to the reviewed context", "RESOLUTION_CONTEXT_MISMATCH");
  }
  if (!resolution.resolver || !["human", "reviewer", "lawyer"].includes(resolution.resolver.type)
    || typeof resolution.resolver.id !== "string" || resolution.resolver.id.length === 0
    || typeof resolution.resolver.session_id !== "string" || resolution.resolver.session_id.length === 0
    || array(resolution.resolved_facts).length === 0
    || typeof resolution.reason !== "string" || resolution.reason.length === 0
    || typeof resolution.resolved_at !== "string" || Number.isNaN(Date.parse(resolution.resolved_at))
    || typeof resolution.lawyer_override !== "boolean"
    || (resolution.lawyer_override && resolution.resolver.type !== "lawyer")) {
    throw new InputError("resolution metadata is incomplete", "RESOLUTION_INPUT_INVALID");
  }
}

function reviewObservationMap(review, expectedRound, candidateById, moduleByName) {
  const reviewModules = array(review.modules);
  if (reviewModules.length !== MODULES.length
    || MODULES.some((module) => reviewModules.filter((item) => item.module === module).length !== 1)) {
    throw new InputError(`${expectedRound} review must contain all eight modules`, "REVIEW_MODULE_COVERAGE_MISMATCH");
  }
  const observations = new Map();
  for (const module of reviewModules) {
    const expectedCandidateIds = [...array(moduleByName.get(module.module)?.candidate_ids)].sort();
    const reviewedCandidateIds = [...array(module.candidate_ids)].sort();
    if (!sameJson(expectedCandidateIds, reviewedCandidateIds)
      || !["assessable", "partially_assessable", "not_assessable"].includes(module.assessability)
      || !CONFIDENCE_ORDER.includes(module.confidence)
      || typeof module.reasoning !== "string" || module.reasoning.length === 0
      || !Array.isArray(module.fact_observations)) {
      throw new InputError(`${expectedRound} review does not cover ${module.module} correctly`, "REVIEW_MODULE_COVERAGE_MISMATCH");
    }
    for (const observation of array(module.fact_observations)) {
      const candidate = candidateById.get(observation.candidate_id);
      if (!candidate || candidate.module !== module.module || !Object.hasOwn(observation, "value")) {
        throw new InputError(`invalid ${expectedRound} review observation`, "REVIEW_OBSERVATION_INVALID");
      }
      factorValueAtPath(candidate, observation.fact_path);
      if (!["verified", "supported", "disputed", "unknown"].includes(observation.status)) {
        throw new InputError(`invalid ${expectedRound} observation status`, "REVIEW_OBSERVATION_INVALID");
      }
      if (!validRefList(observation.evidence_refs) || !validRefList(observation.verification_refs)
        || (["verified", "supported"].includes(observation.status) && observation.evidence_refs.length === 0)
        || (observation.status === "verified" && observation.verification_refs.length === 0)) {
        throw new InputError(`invalid ${expectedRound} observation evidence`, "REVIEW_OBSERVATION_EVIDENCE_INVALID");
      }
      const key = `${module.module}:${observation.candidate_id}:${observation.fact_path}`;
      if (observations.has(key)) throw new InputError(`duplicate review observation: ${key}`, "REVIEW_OBSERVATION_DUPLICATE");
      observations.set(key, { ...observation, module: module.module });
    }
    for (const candidateId of expectedCandidateIds) {
      const candidate = candidateById.get(candidateId);
      if (!isRatingRelevantCandidate(candidate)) continue;
      const missingPaths = requiredRiskFactors(candidate.module)
        .map((key) => `factors.${key}`)
        .filter((path) => !observations.has(`${module.module}:${candidateId}:${path}`));
      if (missingPaths.length > 0) {
        throw new InputError(`${expectedRound} review omits rating facts for ${candidateId}: ${missingPaths.join(", ")}`, "REVIEW_FACT_COVERAGE_MISMATCH");
      }
    }
  }
  return observations;
}

function deriveMergedReviewState(base, first, second, resolution = null) {
  const { candidates, modules } = validateAssessmentInput(base);
  const merged = JSON.parse(JSON.stringify(base));
  const candidateById = new Map(merged.candidates.map((candidate) => [candidate.candidate_id, candidate]));
  const moduleByName = new Map(modules.map((module) => [module.module, module]));
  const firstObservations = reviewObservationMap(first, "first", candidateById, moduleByName);
  const secondObservations = reviewObservationMap(second, "second", candidateById, moduleByName);
  const observationKeys = new Set([...firstObservations.keys(), ...secondObservations.keys()]);
  const conflicts = JSON.parse(JSON.stringify(array(base.review?.fact_conflicts)));
  const addConflict = (conflict) => {
    const existing = conflicts.find((item) => item.conflict_id === conflict.conflict_id);
    if (existing) {
      if (!sameJson(existing, conflict)) {
        throw new InputError(`conflict id has inconsistent content: ${conflict.conflict_id}`, "REVIEW_CONFLICT_ID_COLLISION");
      }
      return;
    }
    conflicts.push(conflict);
  };
  for (const key of observationKeys) {
    const firstObservation = firstObservations.get(key);
    const secondObservation = secondObservations.get(key);
    const observation = firstObservation ?? secondObservation;
    const candidate = candidateById.get(observation.candidate_id);
    const valuesAgree = firstObservation && secondObservation && sameJson(firstObservation.value, secondObservation.value);
    const factsSupported = [firstObservation, secondObservation]
      .filter(Boolean)
      .every((item) => ["verified", "supported"].includes(item.status));
    if (firstObservation && secondObservation && valuesAgree && factsSupported) {
      setFactorValueAtPath(candidate, observation.fact_path, observation.value);
      const agreeingObservations = [firstObservation, secondObservation];
      candidate.evidence_refs = [...new Set([...candidate.evidence_refs, ...agreeingObservations.flatMap((item) => array(item.evidence_refs))])];
      candidate.verification_refs = [...new Set([...candidate.verification_refs, ...agreeingObservations.flatMap((item) => array(item.verification_refs))])];
      continue;
    }
    if (!isRatingDecisionPath(candidate.module, observation.fact_path)) continue;
    addConflict({
      conflict_id: `CONFLICT-${sha256(key).slice(0, 24)}`,
      module: observation.module,
      candidate_id: observation.candidate_id,
      fact_path: observation.fact_path,
      first_review_value: firstObservation?.value ?? null,
      second_review_value: secondObservation?.value ?? null,
      rating_material: true,
      status: "unresolved",
    });
  }
  for (const conflict of [...array(first.fact_conflicts), ...array(second.fact_conflicts)]) {
    const candidate = candidateById.get(conflict.candidate_id);
    if (!candidate || candidate.module !== conflict.module || conflict.status !== "unresolved" || conflict.rating_material !== true
      || !isRatingDecisionPath(candidate.module, conflict.fact_path)) {
      throw new InputError("reviews may only submit unresolved rating-fact conflicts", "REVIEW_CONFLICT_INVALID");
    }
    factorValueAtPath(candidate, conflict.fact_path);
    addConflict({ ...conflict });
  }

  if (resolution) {
    const resolvedFactIds = new Set();
    for (const resolvedFact of array(resolution.resolved_facts)) {
      if (resolvedFactIds.has(resolvedFact.conflict_id)) {
        throw new InputError(`resolution repeats conflict ${resolvedFact.conflict_id}`, "RESOLUTION_INPUT_INVALID");
      }
      resolvedFactIds.add(resolvedFact.conflict_id);
      const conflict = conflicts.find((item) => item.conflict_id === resolvedFact.conflict_id);
      if (!conflict || conflict.status !== "unresolved" || conflict.module !== resolvedFact.module
        || conflict.candidate_id !== resolvedFact.candidate_id || conflict.fact_path !== resolvedFact.fact_path
        || !validRefList(resolvedFact.evidence_refs, { nonEmpty: true })) {
        throw new InputError(`resolution does not match conflict ${resolvedFact.conflict_id}`, "RESOLUTION_CONFLICT_MISMATCH");
      }
      const candidate = candidateById.get(resolvedFact.candidate_id);
      setFactorValueAtPath(candidate, resolvedFact.fact_path, resolvedFact.resolved_value);
      conflict.status = resolution.lawyer_override ? "resolved_by_lawyer" : "resolved_by_human";
      conflict.resolution_value = resolvedFact.resolved_value;
      conflict.resolution_evidence_refs = [...new Set(array(resolvedFact.evidence_refs))];
    }
  }
  for (const conflict of conflicts.filter((item) => String(item.status).startsWith("resolved_by_"))) {
    const candidate = candidateById.get(conflict.candidate_id);
    if (Object.hasOwn(conflict, "resolution_value")) setFactorValueAtPath(candidate, conflict.fact_path, conflict.resolution_value);
  }
  merged.review = { ...merged.review, fact_conflicts: conflicts };
  return { merged, conflicts };
}

function mergeReviews(assessmentInputPath, firstReviewPath, secondReviewPath, resolutionPath, outputPath) {
  const base = readJson(assessmentInputPath, "assessment input");
  const { candidates, modules } = validateAssessmentInput(base);
  const first = readJson(firstReviewPath, "first review");
  const second = readJson(secondReviewPath, "second review");
  if (first.task_id !== base.task_id || second.task_id !== base.task_id) throw new InputError("review task mismatch", "REVIEW_TASK_MISMATCH");
  const expectedContextDigest = stableDigest(base);
  const expectedEvidenceDigest = stableDigest(base.candidates);
  validateReviewArtifact(first, "first", expectedContextDigest, expectedEvidenceDigest);
  validateReviewArtifact(second, "second", expectedContextDigest, expectedEvidenceDigest);
  if (!first.reviewer || !second.reviewer
    || first.reviewer.id === second.reviewer.id
    || first.reviewer.session_id === second.reviewer.session_id) {
    throw new InputError("second review must use an independent reviewer and session", "SECOND_REVIEW_NOT_INDEPENDENT");
  }
  if (!second.isolation || second.isolation.prior_review_read !== false
    || (second.isolation.mode === "runtime_enforced" && !second.isolation.proof_id)) {
    throw new InputError("second review isolation is not supported by its declaration", "SECOND_REVIEW_ISOLATION_INVALID");
  }

  let resolution = null;
  if (resolutionPath) {
    resolution = readJson(resolutionPath, "human resolution");
    validateResolutionArtifact(resolution, base.task_id, expectedContextDigest, expectedEvidenceDigest);
  }
  const { merged, conflicts } = deriveMergedReviewState(base, first, second, resolution);

  const inputDirectory = dirname(resolve(assessmentInputPath));
  const artifactRoot = basename(inputDirectory) === "v2" ? dirname(inputDirectory) : inputDirectory;
  const contextRelativePath = `normalized/reviews/context-${expectedContextDigest}.json`;
  const firstRelativePath = `normalized/reviews/${first.review_id}.json`;
  const secondRelativePath = `normalized/reviews/${second.review_id}.json`;
  writeJson(join(artifactRoot, contextRelativePath), base);
  writeJson(join(artifactRoot, firstRelativePath), first);
  writeJson(join(artifactRoot, secondRelativePath), second);
  const reviewRefs = [first, second].map((review, index) => ({
    review_id: review.review_id,
    round: review.round,
    path: index === 0 ? firstRelativePath : secondRelativePath,
    digest: review.digest,
    context_digest: review.context_digest,
    evidence_digest: review.evidence_digest,
    reviewer_id: review.reviewer.id,
    session_id: review.reviewer.session_id,
  }));
  let resolutionRef = null;
  if (resolution) {
    const resolutionRelativePath = `normalized/resolutions/${resolution.resolution_id}.json`;
    writeJson(join(artifactRoot, resolutionRelativePath), resolution);
    resolutionRef = {
      resolution_id: resolution.resolution_id,
      path: resolutionRelativePath,
      digest: resolution.digest,
    };
  }
  merged.review = {
    ...merged.review,
    fact_conflicts: conflicts,
    review_refs: reviewRefs,
    resolution_ref: resolutionRef,
  };
  validateAssessmentInput(merged);
  const destination = outputPath ?? join(dirname(assessmentInputPath), "assessment-input.merged.json");
  writeJson(destination, merged);
  const evaluation = evaluateAssessment(merged);
  return {
    output_path: destination,
    unresolved_conflict_total: conflicts.filter((conflict) => conflict.status === "unresolved" && conflict.rating_material !== false).length,
    legal_risk: evaluation.overall.legal_risk,
    operational_action: evaluation.overall.operational_action,
    merge_policy: "structured facts are merged and risk is recalculated; review labels are ignored",
  };
}

function finalizeAssessment(taskDir, inputPath) {
  const input = readJson(inputPath, "v2 assessment input");
  const assessment = evaluateAssessment(input);
  validateReviewArtifactBindings(taskDir, input, assessment);
  validateFormalSourceEvidence(taskDir, input, assessment);
  const inputDigest = sha256(input);
  const rulesDigest = rulesFingerprint();
  const productPath = join(taskDir, "02_product_facts.json");
  const queryPlanPath = join(taskDir, "04_query_plan.json");
  const evidencePath = join(taskDir, "05_evidence_ledger.json");
  const sourceManifestPath = join(taskDir, SOURCE_MANIFEST_RELATIVE_PATH);
  const digest = sha256(assessment);
  const finalAssessment = { ...assessment, digest };
  const v2Dir = join(taskDir, "v2");
  writeJson(join(v2Dir, "assessment-input.snapshot.json"), input);
  writeJson(join(v2Dir, "assessment.json"), finalAssessment);
  writeJson(join(v2Dir, "coverage.json"), {
    schema_version: SCHEMA_VERSION,
    ruleset_version: RULESET_VERSION,
    task_id: input.task_id,
    assessment_input_digest: inputDigest,
    ...input.coverage,
  });
  writeJson(join(v2Dir, "decision-trace.json"), {
    schema_version: SCHEMA_VERSION,
    ruleset_version: RULESET_VERSION,
    task_id: assessment.task_id,
    assessment_digest: digest,
    assessment_input_digest: inputDigest,
    rules_digest: rulesDigest,
    product_facts_digest: digestFileOrFallback(productPath, { task_id: input.task_id, artifact: "product_facts", missing: true }),
    query_plan_digest: digestFileOrFallback(queryPlanPath, { task_id: input.task_id, artifact: "query_plan", missing: true }),
    evidence_digest: digestFileOrFallback(evidencePath, assessment.candidate_summaries),
    source_manifest_digest: existsSync(sourceManifestPath) ? sha256(readFileSync(sourceManifestPath)) : null,
    candidate_digest: sha256(assessment.candidate_summaries),
    operational_action: assessment.overall.operational_action,
    operational_action_reason_codes: assessment.decision_trace.reason_codes,
    risk_driver_candidate_ids: assessment.modules.flatMap((module) => module.risk_driver_candidate_ids),
    ...assessment.decision_trace,
  });
  return {
    status: assessment.overall.formal_conclusion_allowed ? "final" : "incomplete",
    assessment_path: join(v2Dir, "assessment.json"),
    decision_trace_path: join(v2Dir, "decision-trace.json"),
    legal_risk: assessment.overall.legal_risk,
    operational_action: assessment.overall.operational_action,
  };
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

const zh = {
  not_assessable: "未评估", very_low: "极低", low: "低", medium: "中", high: "高", critical: "严重",
  no_lead: "未发现需复核线索", leads_found: "已发现线索", review_required: "需要完成候选复核", blocked: "发现流程受阻",
  proceed: "可继续", proceed_with_conditions: "满足条件后继续", hold_for_evidence: "暂缓并补证", escalate_legal: "升级法律复核",
  appearance_design: "外观设计", utility_patent: "实用专利", pending_patent: "申请中专利", word_mark: "文字商标",
  figurative_mark: "图形商标", trade_dress: "商业外观", copyright_creative_ip: "版权/创意资产", enforcement_public_signals: "公开维权信号",
};

function digestFileOrFallback(path, fallback) {
  return existsSync(path) ? sha256(readFileSync(path)) : sha256(fallback);
}

function reportableCandidate(candidate) {
  const evidenceRefs = [...new Set(array(candidate.evidence_refs))];
  if (evidenceRefs.length === 0 || candidate.legal_materiality === "not_material") return null;
  const allowedStatuses = new Set([
    "active", "pending", "expired", "cancelled", "abandoned", "rejected",
    "disputed", "unknown", "not_found", "not_applicable",
  ]);
  const rawStatus = factor(candidate, "right_status", candidate.record_kind === "application" ? "pending" : "unknown");
  const rightStatus = NON_RIGHT_KINDS.has(candidate.record_kind)
    ? "not_applicable"
    : (allowedStatuses.has(rawStatus) ? rawStatus : "unknown");
  return {
    candidate_id: candidate.candidate_id,
    module: candidate.module,
    record_kind: candidate.record_kind,
    legal_materiality: candidate.legal_materiality,
    risk_driver_eligible: candidate.risk_driver_eligible === true,
    authority_tier: candidate.authority_tier,
    evidence_role: candidate.evidence_role,
    evidence_cluster_id: candidate.evidence_cluster_id,
    duplicate_of: candidate.duplicate_of ?? null,
    independence_group: candidate.independence_group,
    record_number: candidate.record_number ?? null,
    title: candidate.title ?? null,
    owner: candidate.owner ?? null,
    right_status: rightStatus,
    target_jurisdiction: candidate.target_jurisdiction ?? "US",
    source_jurisdiction: candidate.source_jurisdiction ?? null,
    right_jurisdiction: candidate.right_jurisdiction ?? null,
    source_locator: candidate.source_locator ?? evidenceRefs[0] ?? null,
    published_at: candidate.published_at ?? null,
    first_seen_at: candidate.first_seen_at ?? null,
    evidence_refs: evidenceRefs,
    verification_refs: [...new Set(array(candidate.verification_refs))],
    summary: candidate.title
      ? `${candidate.title}（${candidate.legal_materiality}）`
      : `${zh[candidate.module] ?? candidate.module}候选（${candidate.legal_materiality}）`,
  };
}

function reportData(taskDir, assessment) {
  const productPath = join(taskDir, "02_product_facts.json");
  const queryPlanPath = join(taskDir, "04_query_plan.json");
  const evidencePath = join(taskDir, "05_evidence_ledger.json");
  const sourceManifestPath = join(taskDir, SOURCE_MANIFEST_RELATIVE_PATH);
  const coveragePath = join(taskDir, "v2", "coverage.json");
  const product = existsSync(productPath) ? readJson(productPath, "product facts") : {};
  const productData = product.product ?? product;
  const productFactValue = (key, fallback) => product.facts?.[key]?.value ?? productData[key] ?? fallback;
  const storedCoverage = existsSync(coveragePath) ? readJson(coveragePath, "v2 coverage") : null;
  const gaps = array(storedCoverage?.gaps).map((gap) => ({
    code: gap.code ?? "UNSPECIFIED_EVIDENCE_GAP",
    scope_type: MODULES.includes(gap.module) ? "module" : "task",
    scope_id: MODULES.includes(gap.module) ? gap.module : assessment.task_id,
    message: gap.detail ?? gap.message ?? gap.code ?? "证据缺口待补充。",
    blocking: gap.blocking !== false,
    effect: gap.blocking !== false ? "formal_block" : "confidence_cap",
  }));
  const coverage = {
    required_total: MODULES.length,
    completed_total: assessment.modules.filter((module) => module.assessability !== "not_assessable").length,
    gap_total: gaps.length,
    confidence: storedCoverage?.confidence ?? assessment.overall.coverage_confidence,
    complete: storedCoverage?.complete === true && gaps.every((gap) => !gap.blocking),
  };

  const finalDriverIds = new Set(assessment.modules.flatMap((module) => array(module.risk_driver_candidate_ids)));
  const representativeCandidates = new Map();
  for (const candidate of array(assessment.candidate_summaries)) {
    const reportCandidate = reportableCandidate(candidate);
    if (!reportCandidate) continue;
    const key = `${reportCandidate.module}:${reportCandidate.evidence_cluster_id}`;
    const existing = representativeCandidates.get(key);
    const reportCandidateIsFinalDriver = finalDriverIds.has(reportCandidate.candidate_id);
    const existingIsFinalDriver = existing ? finalDriverIds.has(existing.candidate_id) : false;
    if (!existing
      || (reportCandidateIsFinalDriver && !existingIsFinalDriver)
      || (reportCandidateIsFinalDriver === existingIsFinalDriver
        && reportCandidate.candidate_id.localeCompare(existing.candidate_id) < 0)) {
      representativeCandidates.set(key, reportCandidate);
    }
  }
  const candidates = [...representativeCandidates.values()];
  const candidateById = new Map(candidates.map((candidate) => [candidate.candidate_id, candidate]));
  const formal = assessment.overall.formal_conclusion_allowed === true;
  const modules = [...assessment.modules]
    .sort((left, right) => MODULES.indexOf(left.module) - MODULES.indexOf(right.module))
    .map((module) => {
      const moduleCandidates = candidates.filter((candidate) => candidate.module === module.module);
      const driverRefs = array(module.risk_driver_candidate_ids)
        .flatMap((candidateId) => array(candidateById.get(candidateId)?.evidence_refs));
      return {
        module: module.module,
        assessability: module.assessability,
        legal_risk: formal ? module.legal_risk : "not_assessable",
        risk_confidence: formal ? module.risk_confidence : "low",
        summary: module.reasoning || "未记录补充说明。",
        risk_driver_ids: array(module.risk_driver_candidate_ids),
        evidence_refs: [...new Set(driverRefs.length > 0
          ? driverRefs
          : moduleCandidates.flatMap((candidate) => candidate.evidence_refs))],
        recommended_actions: array(module.recommended_actions),
      };
    });

  const legalBoundary = "本报告是基于已记录证据的知识产权风险筛查，不是法律意见，也不替代律师的自由实施、有效性或侵权分析。";
  const overview = {
    status: formal ? "正式评估已完成" : "评估尚未完成",
    discovery_status: assessment.overall.discovery_status,
    legal_risk: assessment.overall.legal_risk,
    risk_confidence: assessment.overall.risk_confidence,
    coverage_confidence: assessment.overall.coverage_confidence,
    operational_action: assessment.overall.operational_action,
    formal_conclusion_allowed: formal,
    legal_risk_label: formal ? (zh[assessment.overall.legal_risk] ?? assessment.overall.legal_risk) : "评估尚未完成",
    legacy_risk_seal_visible: false,
    summary: formal
      ? `法律风险${zh[assessment.overall.legal_risk] ?? assessment.overall.legal_risk}；运营建议${zh[assessment.overall.operational_action] ?? assessment.overall.operational_action}。`
      : `发现层已记录 ${assessment.discovery_summary.raw_candidate_count} 条候选；正式 Assessment 尚未完成。`,
    legal_boundary: legalBoundary,
  };

  const appliedConstraints = gaps.map((gap) => ({
    code: gap.code,
    kind: gap.blocking ? "formal_conclusion_blocked" : "confidence_cap",
    effect: gap.effect,
    reason: gap.message,
  }));
  if (assessment.constraints.human_resolution_required) {
    appliedConstraints.push({
      code: "HUMAN_RESOLUTION_REQUIRED",
      kind: "formal_conclusion_blocked",
      effect: "not_assessable",
      reason: "评级驱动事实存在未解决冲突。",
    });
  }

  const candidateSummaryById = new Map(array(assessment.candidate_summaries).map((candidate) => [candidate.candidate_id, candidate]));
  const reasonCodes = [...new Set(array(assessment.decision_trace.reason_codes))];
  const traceEvents = reasonCodes.map((code) => {
    const evaluations = array(assessment.decision_trace.candidate_evaluations)
      .filter((evaluation) => array(evaluation.basis_codes).includes(code));
    const candidateIds = [...new Set(evaluations.map((evaluation) => evaluation.candidate_id))];
    const evidenceRefs = [...new Set(candidateIds.flatMap((candidateId) => (
      array(candidateSummaryById.get(candidateId)?.evidence_refs)
    )))];
    return {
      code,
      message: `v2 规则命中：${code}`,
      rule_ids: [`R2_${code}`],
      candidate_ids: candidateIds,
      evidence_refs: evidenceRefs,
    };
  });
  const evidenceLedger = existsSync(evidencePath) ? readJson(evidencePath, "evidence ledger") : {};
  const base = {
    schema_version: SCHEMA_VERSION,
    ruleset_version: RULESET_VERSION,
    task_id: assessment.task_id,
    report_mode: formal ? "formal" : "draft",
    product: {
      asin: productData.asin ?? null,
      title: productFactValue("title", "未命名商品"),
      brand: productFactValue("brand", ""),
      marketplace: productData.marketplace ?? product.marketplace ?? "US",
    },
    overview,
    discovery_summary: assessment.discovery_summary,
    coverage,
    gaps,
    modules,
    candidates,
    constraints: {
      formal_conclusion_allowed: formal,
      second_review_required: false,
      human_resolution_required: assessment.constraints.human_resolution_required === true,
      applied: appliedConstraints,
    },
    trace: {
      ruleset_version: RULESET_VERSION,
      product_facts_digest: digestFileOrFallback(productPath, { task_id: assessment.task_id, artifact: "product_facts", missing: true }),
      query_plan_digest: digestFileOrFallback(queryPlanPath, { task_id: assessment.task_id, artifact: "query_plan", missing: true }),
      evidence_digest: digestFileOrFallback(evidencePath, assessment.candidate_summaries),
      source_manifest_digest: existsSync(sourceManifestPath) ? sha256(readFileSync(sourceManifestPath)) : null,
      assessment_digest: assessment.digest ?? null,
      evidence_revision: Number.isInteger(evidenceLedger.evidence_revision)
        ? evidenceLedger.evidence_revision
        : (Number.isInteger(evidenceLedger.revision) ? evidenceLedger.revision : 1),
      decision_trace: traceEvents,
    },
    generated_at: now(),
  };
  return { ...base, digest: sha256(base) };
}

function renderHtml(data) {
  const summary = data.overview;
  const draft = !summary.formal_conclusion_allowed;
  const modules = data.modules.map((module) => `
    <article class="module">
      <div class="module-head"><h3>${escapeHtml(zh[module.module] ?? module.module)}</h3><span class="risk risk-${escapeHtml(module.legal_risk)}">${escapeHtml(zh[module.legal_risk] ?? module.legal_risk)}</span></div>
      <div class="meta">可评估性：${escapeHtml(module.assessability)} · 风险置信度：${escapeHtml(zh[module.risk_confidence] ?? module.risk_confidence)}</div>
      <p>${escapeHtml(module.summary || "无补充说明")}</p>
      <div class="codes">${array(module.risk_driver_ids).map((id) => `<code>${escapeHtml(id)}</code>`).join(" ")}</div>
    </article>`).join("");
  const candidates = data.candidates.length > 0
    ? `<div class="candidate-list">${data.candidates.map((candidate) => `<article class="candidate"><div><strong>${escapeHtml(candidate.title || candidate.candidate_id)}</strong><div class="meta">${escapeHtml(zh[candidate.module] ?? candidate.module)} · ${escapeHtml(candidate.legal_materiality)} · ${escapeHtml(candidate.authority_tier)} · 证据组 ${escapeHtml(candidate.evidence_cluster_id)}</div></div><div class="refs">${candidate.evidence_refs.map((ref) => `<code>${escapeHtml(ref)}</code>`).join(" ")}</div></article>`).join("")}</div>`
    : "<p class=\"meta\">没有可展示的已引用候选。</p>";
  return `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>知识产权风险筛查 v2</title>
<style>
:root{--ink:#16202a;--muted:#66717e;--line:#dfe5eb;--paper:#f5f7fa;--card:#fff;--blue:#174ea6;--amber:#9a5b00;--red:#a4262c;--green:#176b3a}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.wrap{max-width:1060px;margin:0 auto;padding:36px 22px 64px}.hero,.module,.panel{background:var(--card);border:1px solid var(--line);border-radius:16px}.hero{padding:28px}.eyebrow{color:var(--blue);font-weight:700;letter-spacing:.08em;text-transform:uppercase}.hero h1{margin:6px 0 18px;font-size:30px}.draft{margin:0 0 18px;padding:12px 14px;border-radius:10px;background:#fff3cd;color:#704b00;font-weight:700}.summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.metric{padding:14px;border-radius:12px;background:#f7f9fc}.metric span{display:block;color:var(--muted);font-size:12px}.metric strong{display:block;margin-top:4px;font-size:20px}.panel{margin-top:18px;padding:20px}.panel h2{margin:0 0 10px}.counts{display:flex;gap:20px;flex-wrap:wrap}.counts b{font-size:22px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:18px}.module{padding:18px}.module-head{display:flex;align-items:center;justify-content:space-between;gap:12px}.module h3{margin:0}.meta{color:var(--muted);font-size:13px}.risk{font-weight:800}.risk-high,.risk-critical{color:var(--red)}.risk-medium{color:var(--amber)}.risk-low,.risk-very_low{color:var(--green)}.risk-not_assessable{color:var(--muted)}code{display:inline-block;margin:2px 3px 0 0;padding:2px 6px;border-radius:5px;background:#edf1f5;font-size:11px;overflow-wrap:anywhere}.candidate-list{display:grid;gap:10px}.candidate{padding:13px 0;border-top:1px solid var(--line)}.candidate:first-child{border-top:0}.refs{margin-top:6px}.boundary{color:var(--muted);font-size:13px}@media(max-width:760px){.summary,.grid{grid-template-columns:1fr 1fr}}@media(max-width:520px){.summary,.grid{grid-template-columns:1fr}}
</style></head><body><main class="wrap"><section class="hero"><div class="eyebrow">IPR Screening · Ruleset ${escapeHtml(data.ruleset_version)}</div><h1>${escapeHtml(data.product.title || "知识产权风险筛查")}</h1>
${draft ? '<div class="draft">评估尚未完成：以下只显示发现进度，不构成正式高低风险结论。</div>' : ""}
<div class="summary"><div class="metric"><span>法律风险</span><strong>${escapeHtml(summary.legal_risk_label)}</strong></div><div class="metric"><span>风险置信度</span><strong>${escapeHtml(zh[summary.risk_confidence] ?? summary.risk_confidence)}</strong></div><div class="metric"><span>覆盖置信度</span><strong>${escapeHtml(zh[summary.coverage_confidence] ?? summary.coverage_confidence)}</strong></div><div class="metric"><span>运营决策</span><strong>${escapeHtml(zh[summary.operational_action] ?? summary.operational_action)}</strong></div></div></section>
<section class="panel"><h2>发现概览</h2><p>状态：<strong>${escapeHtml(zh[data.discovery_summary.status] ?? data.discovery_summary.status)}</strong></p><div class="counts"><span><b>${data.discovery_summary.raw_candidate_count}</b><br>原始候选</span><span><b>${data.discovery_summary.unique_evidence_cluster_count}</b><br>独立证据组</span><span><b>${data.discovery_summary.risk_driver_count}</b><br>风险驱动候选</span><span><b>${data.discovery_summary.contextual_lead_count}</b><br>背景/来源线索</span></div></section>
<section class="grid">${modules}</section><section class="panel"><h2>去重后的候选与证据</h2>${candidates}</section><section class="panel boundary"><strong>边界说明</strong><p>${escapeHtml(summary.legal_boundary)}</p><p>任务：${escapeHtml(data.task_id)} · Assessment：${escapeHtml(data.trace.assessment_digest)} · Ruleset：${escapeHtml(data.ruleset_version)}</p></section></main></body></html>`;
}

function renderMarkdown(data) {
  const s = data.overview;
  const lines = [
    "# 知识产权风险筛查 v2",
    "",
    `- 报告模式：${data.report_mode}`,
    `- 法律风险：${s.legal_risk_label}`,
    `- 风险置信度：${zh[s.risk_confidence] ?? s.risk_confidence}`,
    `- 覆盖置信度：${zh[s.coverage_confidence] ?? s.coverage_confidence}`,
    `- 运营决策：${zh[s.operational_action] ?? s.operational_action}`,
    `- 发现状态：${zh[data.discovery_summary.status] ?? data.discovery_summary.status}`,
    "",
  ];
  if (!s.formal_conclusion_allowed) lines.push("> 评估尚未完成；发现线索不得解释为正式高低风险结论。", "");
  lines.push("## 模块结论", "");
  for (const module of data.modules) {
    lines.push(`### ${zh[module.module] ?? module.module}`, "", `- 法律风险：${zh[module.legal_risk] ?? module.legal_risk}`, `- 风险置信度：${zh[module.risk_confidence] ?? module.risk_confidence}`, `- 风险驱动候选：${array(module.risk_driver_ids).join(", ") || "无"}`, `- 证据引用：${array(module.evidence_refs).join(", ") || "无"}`, "", module.summary || "无补充说明", "");
  }
  lines.push("## 去重后的候选与证据", "");
  for (const candidate of data.candidates) {
    lines.push(`- ${candidate.title || candidate.candidate_id}：${candidate.legal_materiality}；证据组 ${candidate.evidence_cluster_id}；${candidate.evidence_refs.join(", ")}`);
  }
  if (data.candidates.length === 0) lines.push("- 没有可展示的已引用候选。");
  lines.push("", "## 法律边界", "", s.legal_boundary, "");
  return `${lines.join("\n")}\n`;
}

function buildManifest(reportDir, files, data) {
  const artifacts = files.map((name) => {
    const path = join(reportDir, name);
    const content = readFileSync(path);
    return { name, sha256: sha256(content), bytes: statSync(path).size };
  });
  const base = {
    schema_version: SCHEMA_VERSION,
    ruleset_version: RULESET_VERSION,
    rules_digest: rulesFingerprint(),
    task_id: data.task_id,
    report_mode: data.report_mode,
    formal_conclusion_allowed: data.overview.formal_conclusion_allowed,
    report_data_digest: artifacts.find((artifact) => artifact.name === "report_data.json")?.sha256,
    assessment_digest: data.trace.assessment_digest,
    generated_at: now(),
    artifacts,
  };
  return { ...base, manifest_digest: sha256(base) };
}

function renderReport(taskDir) {
  const assessmentPath = join(taskDir, "v2", "assessment.json");
  const assessment = readJson(assessmentPath, "v2 assessment");
  const assessmentInput = readJson(join(taskDir, "v2", "assessment-input.snapshot.json"), "assessment input snapshot");
  validateAssessmentInput(assessmentInput);
  const { digest: assessmentDigest, ...assessmentBase } = assessment;
  if (assessmentDigest !== sha256(assessmentBase)) {
    throw new InputError("assessment digest mismatch", "ASSESSMENT_DIGEST_MISMATCH");
  }
  validateReviewArtifactBindings(taskDir, assessmentInput, assessment);
  if (assessment.overall.formal_conclusion_allowed) validateFormalSourceEvidence(taskDir, assessmentInput, assessment);
  const recalculated = evaluateAssessment(assessmentInput);
  const comparableAssessment = JSON.parse(JSON.stringify(assessmentBase));
  comparableAssessment.decision_trace.evaluated_at = null;
  recalculated.decision_trace.evaluated_at = null;
  if (!sameJson(comparableAssessment, recalculated)) {
    throw new InputError("assessment no longer matches its inputs and rules", "ASSESSMENT_RECALCULATION_MISMATCH");
  }
  const data = reportData(taskDir, assessment);
  const reportDir = join(taskDir, "report-v2");
  mkdirSync(reportDir, { recursive: true });
  const dataName = "report_data.json";
  const htmlName = "ipr-risk-screening-report.html";
  const mdName = "ipr-risk-screening-report.md";
  writeJson(join(reportDir, dataName), data);
  writeFileSync(join(reportDir, htmlName), renderHtml(data), "utf8");
  writeFileSync(join(reportDir, mdName), renderMarkdown(data), "utf8");
  const manifest = buildManifest(reportDir, [dataName, htmlName, mdName], data);
  writeJson(join(reportDir, "manifest.json"), manifest);
  return { report_directory: reportDir, report_mode: data.report_mode, legal_risk: data.overview.legal_risk };
}

function validateReviewArtifactBindings(taskDir, assessmentInput, assessment = null) {
  const reviewRefs = array(assessmentInput.review?.review_refs);
  const resolutionRef = assessmentInput.review?.resolution_ref ?? null;
  if (reviewRefs.length === 0) {
    if (assessment?.review_refs || assessment?.resolution_ref) {
      throw new InputError("assessment contains review references absent from its input", "REVIEW_ARTIFACT_BINDING_MISMATCH");
    }
    return;
  }
  if (assessment && (!sameJson(assessment.review_refs, reviewRefs)
    || !sameJson(assessment.resolution_ref ?? null, resolutionRef))) {
    throw new InputError("assessment review references do not match its input", "REVIEW_ARTIFACT_BINDING_MISMATCH");
  }
  const sharedContextDigest = reviewRefs[0].context_digest;
  const sharedEvidenceDigest = reviewRefs[0].evidence_digest;
  const contextPath = join(taskDir, `normalized/reviews/context-${sharedContextDigest}.json`);
  const reviewedContext = readJson(contextPath, "review context snapshot");
  if (stableDigest(reviewedContext) !== sharedContextDigest
    || stableDigest(reviewedContext.candidates) !== sharedEvidenceDigest
    || reviewedContext.task_id !== assessmentInput.task_id) {
    throw new InputError("review context snapshot is missing or does not match the references", "REVIEW_CONTEXT_BINDING_MISMATCH");
  }
  const { candidates: contextCandidates, modules: contextModules } = validateAssessmentInput(reviewedContext);
  const contextCandidateById = new Map(contextCandidates.map((candidate) => [candidate.candidate_id, candidate]));
  const contextModuleByName = new Map(contextModules.map((module) => [module.module, module]));
  const reviewArtifacts = [];
  for (const ref of reviewRefs) {
    const review = readJson(join(taskDir, ref.path), `${ref.round} review artifact`);
    validateReviewArtifact(review, ref.round, sharedContextDigest, sharedEvidenceDigest);
    reviewObservationMap(review, ref.round, contextCandidateById, contextModuleByName);
    if (review.review_id !== ref.review_id || review.round !== ref.round
      || review.task_id !== assessmentInput.task_id
      || review.digest !== ref.digest || review.digest !== immutableArtifactDigest(review)
      || review.context_digest !== ref.context_digest || review.evidence_digest !== ref.evidence_digest
      || review.reviewer?.id !== ref.reviewer_id || review.reviewer?.session_id !== ref.session_id
      || array(review.fact_conflicts).some((conflict) => conflict.status !== "unresolved")) {
      throw new InputError(`review artifact binding failed: ${ref.review_id}`, "REVIEW_ARTIFACT_BINDING_MISMATCH");
    }
    if (review.context_digest !== sharedContextDigest || review.evidence_digest !== sharedEvidenceDigest) {
      throw new InputError("review artifacts do not share one frozen context", "REVIEW_ARTIFACT_BINDING_MISMATCH");
    }
    reviewArtifacts.push(review);
  }
  if (reviewArtifacts[0].reviewer.id === reviewArtifacts[1].reviewer.id
    || reviewArtifacts[0].reviewer.session_id === reviewArtifacts[1].reviewer.session_id) {
    throw new InputError("review artifacts are not independent", "SECOND_REVIEW_NOT_INDEPENDENT");
  }
  let resolution = null;
  if (resolutionRef) {
    resolution = readJson(join(taskDir, resolutionRef.path), "resolution artifact");
    validateResolutionArtifact(resolution, assessmentInput.task_id, sharedContextDigest, sharedEvidenceDigest);
    if (resolution.resolution_id !== resolutionRef.resolution_id
      || resolution.task_id !== assessmentInput.task_id
      || resolution.digest !== resolutionRef.digest
      || resolution.digest !== immutableArtifactDigest(resolution)
      || resolution.context_digest !== sharedContextDigest
      || resolution.evidence_digest !== sharedEvidenceDigest) {
      throw new InputError("resolution artifact binding failed", "RESOLUTION_ARTIFACT_BINDING_MISMATCH");
    }
    const resolvedById = new Map(array(resolution.resolved_facts).map((fact) => [fact.conflict_id, fact]));
    for (const conflict of array(assessmentInput.review.fact_conflicts).filter((item) => String(item.status).startsWith("resolved_by_"))) {
      const fact = resolvedById.get(conflict.conflict_id);
      if (!fact || fact.candidate_id !== conflict.candidate_id || fact.fact_path !== conflict.fact_path
        || !sameJson(fact.resolved_value, conflict.resolution_value)
        || !sameJson([...array(fact.evidence_refs)].sort(), [...array(conflict.resolution_evidence_refs)].sort())) {
        throw new InputError(`resolution artifact does not support ${conflict.conflict_id}`, "RESOLUTION_ARTIFACT_BINDING_MISMATCH");
      }
    }
  }
  const replayed = deriveMergedReviewState(reviewedContext, reviewArtifacts[0], reviewArtifacts[1], resolution).merged;
  replayed.review = {
    ...replayed.review,
    review_refs: reviewRefs,
    resolution_ref: resolutionRef,
  };
  if (!sameJson(replayed, assessmentInput)) {
    throw new InputError("assessment input does not equal the immutable review merge result", "REVIEW_MERGE_BINDING_MISMATCH");
  }
}

function safeBoundArtifactPath(taskDir, relativePath, pattern, code) {
  if (typeof relativePath !== "string" || !pattern.test(relativePath)) {
    throw new InputError(`unsafe or invalid artifact path: ${relativePath}`, code);
  }
  const root = resolve(taskDir);
  const absolutePath = resolve(root, relativePath);
  if (!absolutePath.startsWith(`${root}/`)) throw new InputError(`artifact escapes task directory: ${relativePath}`, code);
  return absolutePath;
}

function validSha(value) {
  return typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
}

function validDateTime(value) {
  return typeof value === "string" && !Number.isNaN(Date.parse(value));
}

const SOURCE_MANIFEST_RELATIVE_PATH = "v2/source-manifest.json";

function sourceArtifactPaths(taskDir, product, ledger) {
  const paths = new Set([
    "02_product_facts.json",
    "04_query_plan.json",
    "05_evidence_ledger.json",
    "checkpoints/coverage.json",
  ]);
  if (existsSync(join(taskDir, "01_task.json"))) paths.add("01_task.json");
  const addPath = (relativePath) => {
    if (typeof relativePath !== "string" || relativePath.length === 0) return;
    safeBoundArtifactPath(taskDir, relativePath, /^(?!.*(?:^|\/)\.\.(?:\/|$)).+/, "SOURCE_MANIFEST_INVALID");
    paths.add(relativePath);
  };
  for (const image of array(product.images)) addPath(image?.path);
  for (const declaration of array(product.provenance_declarations)) {
    if (array(product.images).some((image) => image?.path === declaration?.asset_ref)
      || /^(?:input-images|raw|screenshots)\//.test(declaration?.asset_ref ?? "")) {
      addPath(declaration.asset_ref);
    }
    for (const ref of array(declaration?.evidence_refs)) {
      if (/^(?:raw|screenshots)\//.test(ref)) addPath(ref);
    }
  }
  for (const run of array(ledger.provider_runs)) {
    addPath(run?.result_path);
    if (typeof run?.result_path === "string" && existsSync(join(taskDir, run.result_path))) {
      const result = readJson(join(taskDir, run.result_path), `provider result ${run.run_id ?? "unknown"}`);
      addPath(result.raw_path);
    }
  }
  for (const evidence of array(ledger.evidence_items)) {
    for (const ref of array(evidence?.raw_refs)) addPath(ref);
  }
  for (const entry of [...array(ledger.official_verifications), ...array(ledger.copyright_provenance_verifications)]) {
    addPath(entry?.event_path);
    if (typeof entry?.event_path === "string" && existsSync(join(taskDir, entry.event_path))) {
      const event = readJson(join(taskDir, entry.event_path), `verification event ${entry.verification_id ?? "unknown"}`);
      if (typeof event.asset_ref === "string") addPath(event.asset_ref);
      for (const proof of array(event.proof_refs)) addPath(proof?.path);
    }
  }
  return [...paths].sort();
}

function buildSourceManifest(taskDir, taskId, product, ledger, { revision = 1, parentDigest = null, sealedAt = now() } = {}) {
  const artifacts = sourceArtifactPaths(taskDir, product, ledger).map((relativePath) => {
    const absolutePath = safeBoundArtifactPath(
      taskDir,
      relativePath,
      /^(?!.*(?:^|\/)\.\.(?:\/|$)).+/,
      "SOURCE_MANIFEST_INVALID",
    );
    if (!existsSync(absolutePath) || !statSync(absolutePath).isFile()) {
      throw new InputError(`source artifact is missing: ${relativePath}`, "SOURCE_MANIFEST_INVALID");
    }
    const content = readFileSync(absolutePath);
    return { path: relativePath, sha256: sha256(content), bytes: content.length };
  });
  const manifest = {
    schema_version: SCHEMA_VERSION,
    ruleset_version: RULESET_VERSION,
    task_id: taskId,
    revision,
    parent_digest: parentDigest,
    sealed_at: sealedAt,
    artifacts,
  };
  return { ...manifest, digest: immutableArtifactDigest(manifest) };
}

function writeSourceManifest(taskDir, taskId, product, ledger, options = {}) {
  const manifest = buildSourceManifest(taskDir, taskId, product, ledger, options);
  writeJson(join(taskDir, SOURCE_MANIFEST_RELATIVE_PATH), manifest);
  return manifest;
}

function validateSourceManifest(taskDir, taskId, product, ledger) {
  const manifestPath = join(taskDir, SOURCE_MANIFEST_RELATIVE_PATH);
  if (!existsSync(manifestPath)) {
    throw new InputError("formal release requires a v2 frozen-source manifest", "SOURCE_MANIFEST_REQUIRED");
  }
  const manifest = readJson(manifestPath, "v2 frozen-source manifest");
  const allowedKeys = ["schema_version", "ruleset_version", "task_id", "revision", "parent_digest", "sealed_at", "artifacts", "digest"];
  if (!manifest || manifest.schema_version !== SCHEMA_VERSION || manifest.ruleset_version !== RULESET_VERSION
    || manifest.task_id !== taskId || !Number.isInteger(manifest.revision) || manifest.revision < 1
    || (manifest.parent_digest !== null && !validSha(manifest.parent_digest))
    || !validDateTime(manifest.sealed_at) || !validSha(manifest.digest)
    || manifest.digest !== immutableArtifactDigest(manifest)
    || !Array.isArray(manifest.artifacts) || manifest.artifacts.length === 0
    || Object.keys(manifest).some((key) => !allowedKeys.includes(key))) {
    throw new InputError("v2 frozen-source manifest contract is invalid", "SOURCE_MANIFEST_INVALID");
  }
  const expectedPaths = sourceArtifactPaths(taskDir, product, ledger);
  const actualPaths = manifest.artifacts.map((artifact) => artifact?.path);
  if (new Set(actualPaths).size !== actualPaths.length || !sameJson([...actualPaths].sort(), expectedPaths)) {
    throw new InputError("v2 frozen-source manifest does not cover the current source graph", "SOURCE_MANIFEST_MISMATCH");
  }
  for (const artifact of manifest.artifacts) {
    if (!artifact || Object.keys(artifact).some((key) => !["path", "sha256", "bytes"].includes(key))
      || !validSha(artifact.sha256) || !Number.isInteger(artifact.bytes) || artifact.bytes < 0) {
      throw new InputError("v2 frozen-source manifest contains an invalid artifact", "SOURCE_MANIFEST_INVALID");
    }
    const absolutePath = safeBoundArtifactPath(
      taskDir,
      artifact.path,
      /^(?!.*(?:^|\/)\.\.(?:\/|$)).+/,
      "SOURCE_MANIFEST_INVALID",
    );
    if (!existsSync(absolutePath)) {
      throw new InputError(`source artifact is missing: ${artifact.path}`, "SOURCE_MANIFEST_MISMATCH");
    }
    const content = readFileSync(absolutePath);
    if (content.length !== artifact.bytes || sha256(content) !== artifact.sha256) {
      throw new InputError(`source artifact changed after sealing: ${artifact.path}`, "SOURCE_MANIFEST_MISMATCH");
    }
  }
  return manifest;
}

function validateFrozenProductFacts(taskDir, taskId) {
  const productPath = join(taskDir, "02_product_facts.json");
  if (!existsSync(productPath)) {
    throw new InputError("formal release requires frozen product facts", "FORMAL_PRODUCT_FACTS_REQUIRED");
  }
  const product = readJson(productPath, "frozen product facts");
  const allowedKeys = new Set([
    "schema_version", "task_id", "product_id", "marketplace", "asin", "input_mode", "facts",
    "images", "feature_inventory", "provenance_declarations", "frozen_at", "digest",
  ]);
  if (!product || product.schema_version !== "0.1" || product.task_id !== taskId
    || Object.keys(product).some((key) => !allowedKeys.has(key))
    || typeof product.product_id !== "string" || product.product_id.length === 0
    || product.marketplace !== "US"
    || !["asin_lookup", "manual_detail"].includes(product.input_mode)
    || !product.facts || typeof product.facts !== "object"
    || ["title", "brand", "category", "bullet_points", "description", "materials", "technical_functions"]
      .some((key) => !Object.hasOwn(product.facts, key))
    || !Array.isArray(product.images) || product.images.length === 0
    || !Array.isArray(product.feature_inventory)
    || !Array.isArray(product.provenance_declarations)
    || !validDateTime(product.frozen_at) || !validSha(product.digest)) {
    throw new InputError("product facts do not satisfy the frozen 0.1 contract", "FORMAL_PRODUCT_FACTS_INVALID");
  }
  for (const image of product.images) {
    if (!image || typeof image.path !== "string" || !validSha(image.sha256)) {
      throw new InputError("product image inventory is incomplete", "FORMAL_PRODUCT_FACTS_INVALID");
    }
    const imagePath = safeBoundArtifactPath(taskDir, image.path, /^(?!.*(?:^|\/)\.\.(?:\/|$)).+/, "FORMAL_PRODUCT_FACTS_INVALID");
    if (!existsSync(imagePath) || sha256(readFileSync(imagePath)) !== image.sha256) {
      throw new InputError(`product image is missing or stale: ${image.path}`, "FORMAL_PRODUCT_FACTS_INVALID");
    }
  }
  return product;
}

function validateCompleteCreativeProvenance(taskDir, product, evidenceById) {
  const declarations = array(product.provenance_declarations);
  const supplied = declarations.filter((item) => item?.state === "provided");
  if (supplied.length === 0 || declarations.some((item) => item?.state === "unknown")) {
    throw new InputError("very-low/proceed requires a complete creative provenance declaration", "FORMAL_PROVENANCE_INCOMPLETE");
  }
  for (const image of product.images) {
    const matchingDeclarations = supplied.filter((declaration) => (
      declaration.asset_ref === image.path && declaration.asset_sha256 === image.sha256
    ));
    if (matchingDeclarations.length !== 1) {
      throw new InputError(`creative provenance does not uniquely cover product asset: ${image.path}`, "FORMAL_PROVENANCE_INCOMPLETE");
    }
  }
  for (const declaration of supplied) {
    const normalizedScope = String(declaration.license_scope ?? "").toLowerCase();
    const normalizedTerritory = String(declaration.territory ?? "").toUpperCase();
    const normalizedTerm = String(declaration.term ?? "").toLowerCase();
    const negativeScope = /\b(?:no|not|without|prohibited?|excluded?|non-commercial)\b|不(?:得|可|允许|含)|禁止|未授权/i.test(normalizedScope);
    const negativeTerritory = /\b(?:NO|NOT|EXCEPT|EXCLUDE[DS]?)\b|不含|除外/.test(normalizedTerritory);
    const expiredTerm = /\b(?:expired?|ended?|lapsed?|terminated?|revoked?)\b|过期|终止|失效/.test(normalizedTerm);
    if (!validSha(declaration.asset_sha256)
      || !nonBlankString(declaration.creator) || !nonBlankString(declaration.rights_owner)
      || !["original", "license", "assignment", "employment", "commissioned", "public_domain"].includes(declaration.rights_basis)
      || !nonBlankString(declaration.license_scope) || negativeScope
      || !nonBlankString(declaration.territory) || negativeTerritory
      || !/^(?:US|USA|UNITED STATES(?: OF AMERICA)?|WORLDWIDE|GLOBAL)$/.test(normalizedTerritory.trim())
      || !nonBlankString(declaration.term) || expiredTerm
      || !validRefList(declaration.evidence_refs, { nonEmpty: true })) {
      throw new InputError("creative provenance declaration lacks ownership or authorization evidence", "FORMAL_PROVENANCE_INCOMPLETE");
    }
    const declaredImage = product.images.find((image) => image.path === declaration.asset_ref);
    if (declaredImage) {
      if (declaredImage.sha256 !== declaration.asset_sha256) {
        throw new InputError("creative provenance asset digest does not match product facts", "FORMAL_PROVENANCE_INCOMPLETE");
      }
    } else {
      const assetPath = safeBoundArtifactPath(taskDir, declaration.asset_ref, /^(?!.*(?:^|\/)\.\.(?:\/|$)).+/, "FORMAL_PROVENANCE_INCOMPLETE");
      if (!existsSync(assetPath) || sha256(readFileSync(assetPath)) !== declaration.asset_sha256) {
        throw new InputError("creative provenance asset is missing or stale", "FORMAL_PROVENANCE_INCOMPLETE");
      }
    }
    for (const ref of declaration.evidence_refs) {
      if (evidenceById.has(ref)) {
        throw new InputError(`discovery evidence cannot substitute for a provenance proof: ${ref}`, "FORMAL_PROVENANCE_INCOMPLETE");
      }
      const evidencePath = safeBoundArtifactPath(taskDir, ref, /^raw\/copyright-provenance\/.+/, "FORMAL_PROVENANCE_INCOMPLETE");
      if (!existsSync(evidencePath)) {
        throw new InputError(`creative provenance evidence is missing: ${ref}`, "FORMAL_PROVENANCE_INCOMPLETE");
      }
      const proof = readJson(evidencePath, "creative provenance proof");
      const allowedProofKeys = ["schema_version", "task_id", "asset_ref", "asset_sha256", "creator", "rights_owner", "rights_basis", "commercial_use_allowed", "amazon_use_allowed", "territory_includes_us", "term_valid"];
      if (!proof || proof.schema_version !== SCHEMA_VERSION || proof.task_id !== product.task_id
        || Object.keys(proof).some((key) => !allowedProofKeys.includes(key))
        || proof.asset_ref !== declaration.asset_ref || proof.asset_sha256 !== declaration.asset_sha256
        || proof.creator !== declaration.creator || proof.rights_owner !== declaration.rights_owner
        || proof.rights_basis !== declaration.rights_basis
        || proof.commercial_use_allowed !== true || proof.amazon_use_allowed !== true
        || proof.territory_includes_us !== true || proof.term_valid !== true) {
        throw new InputError(`creative provenance evidence does not match its declaration: ${ref}`, "FORMAL_PROVENANCE_INCOMPLETE");
      }
    }
  }
}

function validateFrozenEvidenceLedger(taskDir, ledger, taskId) {
  const requiredTopLevel = [
    "schema_version", "task_id", "revision", "parent_digest", "query_plan_digest",
    "provider_runs", "evidence_items", "candidates", "official_verifications",
    "copyright_provenance_verifications", "updated_at", "digest", "frozen", "frozen_at",
  ];
  if (!ledger || typeof ledger !== "object"
    || requiredTopLevel.some((key) => !Object.hasOwn(ledger, key))
    || Object.keys(ledger).some((key) => !requiredTopLevel.includes(key))
    || ledger.schema_version !== "0.1"
    || ledger.task_id !== taskId
    || !/^ipr_[A-Za-z0-9_-]{8,80}$/.test(ledger.task_id)
    || !Number.isInteger(ledger.revision) || ledger.revision < 1
    || (ledger.parent_digest !== null && !validSha(ledger.parent_digest))
    || !validSha(ledger.query_plan_digest) || !validSha(ledger.digest)
    || !validDateTime(ledger.updated_at) || ledger.frozen !== true || !validDateTime(ledger.frozen_at)
    || !Array.isArray(ledger.provider_runs) || ledger.provider_runs.length === 0
    || !Array.isArray(ledger.evidence_items) || !Array.isArray(ledger.candidates)
    || !Array.isArray(ledger.official_verifications) || !Array.isArray(ledger.copyright_provenance_verifications)) {
    throw new InputError("evidence ledger does not satisfy the frozen 0.1 contract", "HIGH_SOURCE_LEDGER_INVALID");
  }
  const queryPlanPath = join(taskDir, "04_query_plan.json");
  if (!existsSync(queryPlanPath)) {
    throw new InputError("formal release requires a digest-bound query plan", "FORMAL_QUERY_PLAN_REQUIRED");
  }
  const queryPlan = readJson(queryPlanPath, "query plan");
  const product = validateFrozenProductFacts(taskDir, taskId);
  if (queryPlan.schema_version !== "0.1" || queryPlan.task_id !== taskId
    || queryPlan.product_facts_digest !== product.digest
    || !Number.isInteger(queryPlan.plan_version) || queryPlan.plan_version < 1
    || !Array.isArray(queryPlan.items) || queryPlan.items.length === 0
    || !validDateTime(queryPlan.frozen_at) || !validSha(queryPlan.digest)
    || queryPlan.digest !== ledger.query_plan_digest) {
    throw new InputError("evidence ledger is not bound to the current query plan", "HIGH_SOURCE_LEDGER_INVALID");
  }

  const runById = new Map();
  for (const run of ledger.provider_runs) {
    if (!run || !/^RUN-[A-Za-z0-9_-]{4,100}$/.test(run.run_id ?? "")
      || !/^Q-[A-Za-z0-9_-]{4,80}$/.test(run.query_id ?? "")
      || !validSha(run.result_sha256)
      || Object.keys(run).some((key) => !["run_id", "query_id", "result_path", "result_sha256"].includes(key))
      || runById.has(run.run_id)) {
      throw new InputError("provider run metadata is invalid or duplicated", "HIGH_SOURCE_LEDGER_INVALID");
    }
    const resultPath = safeBoundArtifactPath(
      taskDir,
      run.result_path,
      /^normalized\/provider-results\/[A-Za-z0-9][A-Za-z0-9_.-]*\.json$/,
      "HIGH_SOURCE_LEDGER_INVALID",
    );
    if (!existsSync(resultPath) || sha256(readFileSync(resultPath)) !== run.result_sha256) {
      throw new InputError(`provider result is missing or stale: ${run.run_id}`, "HIGH_SOURCE_LEDGER_INVALID");
    }
    const result = readJson(resultPath, `provider result ${run.run_id}`);
    const resultStatusValid = ["success", "no_result", "partial", "failed", "needs_user_action", "access_limited"].includes(result.status);
    const rawPath = typeof result.raw_path === "string"
      ? safeBoundArtifactPath(taskDir, result.raw_path, /^raw\/[^\\/]+$/, "HIGH_SOURCE_LEDGER_INVALID")
      : null;
    if (result.schema_version !== "0.1" || result.task_id !== taskId
      || result.run_id !== run.run_id || result.query_id !== run.query_id
      || !resultStatusValid || !result.parser || result.parser.schema_valid !== true
      || !result.counts || !Number.isInteger(result.counts.items) || result.counts.items < 0
      || !Array.isArray(result.coverage_modules) || result.coverage_modules.length === 0
      || result.coverage_modules.some((module) => !LEGACY_DISCOVERY_MODULES.includes(module))
      || !rawPath || !validSha(result.raw_sha256)
      || !existsSync(rawPath) || sha256(readFileSync(rawPath)) !== result.raw_sha256) {
      throw new InputError(`provider result contract is invalid: ${run.run_id}`, "HIGH_SOURCE_LEDGER_INVALID");
    }
    runById.set(run.run_id, { ...run, result });
  }

  const evidenceById = new Map();
  const sourceByKey = new Map();
  const evidenceKeys = ["evidence_id", "run_id", "source_index", "module", "jurisdiction", "right_type", "record_number", "title", "owner", "source_locator", "summary", "raw_refs"];
  for (const item of ledger.evidence_items) {
    const producingRun = runById.get(item?.run_id);
    if (!item || !/^E-[A-Za-z0-9_-]{4,100}$/.test(item.evidence_id ?? "")
      || evidenceById.has(item.evidence_id) || !producingRun
      || !["success", "partial"].includes(producingRun.result.status)
      || !Number.isInteger(item.source_index) || item.source_index < 0
      || item.source_index >= producingRun.result.counts.items
      || typeof item.module !== "string" || item.module.length === 0
      || !/^[A-Z][A-Z0-9-]{1,15}$/.test(item.jurisdiction ?? "")
      || typeof item.right_type !== "string" || item.right_type.length === 0
      || typeof item.source_locator !== "string" || item.source_locator.length === 0
      || typeof item.summary !== "string" || item.summary.length === 0
      || !validRefList(item.raw_refs, { nonEmpty: true })
      || item.raw_refs.some((ref) => !/^(?:raw|screenshots)\/.+/.test(ref))
      || !item.raw_refs.includes(producingRun.result.raw_path)
      || Object.keys(item).some((key) => !evidenceKeys.includes(key))) {
      throw new InputError("evidence item does not satisfy the ledger contract", "HIGH_SOURCE_LEDGER_INVALID");
    }
    for (const rawRef of item.raw_refs) {
      const rawPath = safeBoundArtifactPath(taskDir, rawRef, /^(?:raw|screenshots)\/.+/, "HIGH_SOURCE_LEDGER_INVALID");
      if (!existsSync(rawPath)) throw new InputError(`raw evidence is missing: ${rawRef}`, "HIGH_SOURCE_LEDGER_INVALID");
    }
    const sourceKey = `${item.run_id}:${item.source_index}`;
    if (sourceByKey.has(sourceKey)) throw new InputError(`duplicate provider source identity: ${sourceKey}`, "HIGH_SOURCE_LEDGER_INVALID");
    evidenceById.set(item.evidence_id, item);
    sourceByKey.set(sourceKey, item);
  }

  const ledgerCandidateById = new Map();
  const candidateKeys = ["candidate_id", "candidate_key", "evidence_refs", "source_refs", "module", "jurisdiction", "right_type", "record_number", "title", "owner", "disposition"];
  for (const candidate of ledger.candidates) {
    if (!candidate || !/^C-[A-Za-z0-9_-]{4,100}$/.test(candidate.candidate_id ?? "")
      || ledgerCandidateById.has(candidate.candidate_id)
      || typeof candidate.candidate_key !== "string" || candidate.candidate_key.length === 0
      || !validRefList(candidate.evidence_refs, { nonEmpty: true })
      || candidate.evidence_refs.some((ref) => !evidenceById.has(ref))
      || !Array.isArray(candidate.source_refs) || candidate.source_refs.length === 0
      || typeof candidate.module !== "string" || candidate.module.length === 0
      || !/^[A-Z][A-Z0-9-]{1,15}$/.test(candidate.jurisdiction ?? "")
      || typeof candidate.right_type !== "string" || candidate.right_type.length === 0
      || Object.keys(candidate).some((key) => !candidateKeys.includes(key))) {
      throw new InputError("ledger candidate does not satisfy the candidate/evidence contract", "HIGH_SOURCE_LEDGER_INVALID");
    }
    const candidateEvidence = new Set(candidate.evidence_refs);
    for (const evidenceRef of candidate.evidence_refs) {
      const evidence = evidenceById.get(evidenceRef);
      const moduleMatches = evidence.module === candidate.module
        || (candidate.module === "figurative_trade_dress" && ["figurative_mark", "trade_dress"].includes(evidence.module))
        || (evidence.module === "figurative_trade_dress" && ["figurative_mark", "trade_dress"].includes(candidate.module));
      if (!moduleMatches || evidence.jurisdiction !== candidate.jurisdiction
        || evidence.right_type !== candidate.right_type
        || (candidate.record_number !== null && candidate.record_number !== undefined
          && evidence.record_number !== candidate.record_number)) {
        throw new InputError(`candidate evidence identity mismatch: ${candidate.candidate_id}`, "HIGH_SOURCE_LEDGER_INVALID");
      }
    }
    for (const sourceRef of candidate.source_refs) {
      if (!sourceRef || Object.keys(sourceRef).some((key) => !["run_id", "source_index"].includes(key))
        || !Number.isInteger(sourceRef.source_index) || !sourceByKey.has(`${sourceRef.run_id}:${sourceRef.source_index}`)
        || !candidateEvidence.has(sourceByKey.get(`${sourceRef.run_id}:${sourceRef.source_index}`).evidence_id)) {
        throw new InputError(`candidate source reference is dangling: ${candidate.candidate_id}`, "HIGH_SOURCE_LEDGER_INVALID");
      }
    }
    ledgerCandidateById.set(candidate.candidate_id, candidate);
  }

  const verificationById = new Map();
  const registerVerification = (verification, copyright) => {
    const idPattern = copyright ? /^CPV-[a-f0-9]{24}$/ : /^V-[A-Za-z0-9_-]{4,100}$/;
    const pathPattern = copyright
      ? /^normalized\/copyright-provenance-verifications\/[A-Za-z0-9][A-Za-z0-9_.-]*\.json$/
      : /^normalized\/official-verifications\/[A-Za-z0-9][A-Za-z0-9_.-]*\.json$/;
    if (!verification || !idPattern.test(verification.verification_id ?? "")
      || !ledgerCandidateById.has(verification.candidate_id) || !validSha(verification.event_sha256)
      || verificationById.has(verification.verification_id)
      || Object.keys(verification).some((key) => !["verification_id", "candidate_id", "event_path", "event_sha256"].includes(key))) {
      throw new InputError("verification ledger entry is invalid", "VERIFICATION_ARTIFACT_INVALID");
    }
    const eventPath = safeBoundArtifactPath(taskDir, verification.event_path, pathPattern, "VERIFICATION_ARTIFACT_INVALID");
    if (!existsSync(eventPath) || sha256(readFileSync(eventPath)) !== verification.event_sha256) {
      throw new InputError(`verification artifact is missing or stale: ${verification.verification_id}`, "VERIFICATION_ARTIFACT_INVALID");
    }
    const event = readJson(eventPath, `${copyright ? "copyright" : "official"} verification event`);
    if (event.verification_id !== verification.verification_id || event.candidate_id !== verification.candidate_id
      || event.task_id !== taskId) {
      throw new InputError(`verification event identity mismatch: ${verification.verification_id}`, "VERIFICATION_ARTIFACT_INVALID");
    }
    if (copyright) {
      const copyrightKeys = ["schema_version", "verification_id", "task_id", "candidate_id", "candidate_key", "evidence_revision", "asset_ref", "asset_sha256", "resolution", "creator", "rights_owner", "rights_basis", "license_scope", "territory", "term", "commercial_use_allowed", "amazon_use_allowed", "proof_refs", "verified_by", "verified_at", "notes", "digest"];
      const assetPath = typeof event.asset_ref === "string"
        ? safeBoundArtifactPath(taskDir, event.asset_ref, /^raw\/.+/, "VERIFICATION_ARTIFACT_INVALID")
        : null;
      if (event.schema_version !== "0.1" || !validSha(event.digest)
        || event.digest !== immutableArtifactDigest(event)
        || Object.keys(event).some((key) => !copyrightKeys.includes(key))
        || typeof event.candidate_key !== "string" || event.candidate_key.length === 0
        || !["owned", "licensed", "unlicensed", "unknown"].includes(event.resolution)
        || !Number.isInteger(event.evidence_revision) || event.evidence_revision < 1
        || !assetPath || !validSha(event.asset_sha256) || !existsSync(assetPath) || sha256(readFileSync(assetPath)) !== event.asset_sha256
        || typeof event.creator !== "string" || typeof event.rights_owner !== "string"
        || !["original", "license", "assignment", "employment", "commissioned", "public_domain", "unknown"].includes(event.rights_basis)
        || typeof event.license_scope !== "string" || typeof event.territory !== "string" || typeof event.term !== "string"
        || typeof event.notes !== "string" || !validDateTime(event.verified_at)
        || typeof event.commercial_use_allowed !== "boolean" || typeof event.amazon_use_allowed !== "boolean"
        || !event.verified_by || !["agent", "human", "backend", "reviewer"].includes(event.verified_by.type)
        || typeof event.verified_by.id !== "string" || event.verified_by.id.length === 0
        || typeof event.verified_by.session_id !== "string" || event.verified_by.session_id.length === 0
        || !Array.isArray(event.proof_refs) || event.proof_refs.length === 0 || event.proof_refs.length > 20) {
        throw new InputError(`copyright verification contract is incomplete: ${verification.verification_id}`, "VERIFICATION_ARTIFACT_INVALID");
      }
      for (const proof of event.proof_refs) {
        if (!proof || Object.keys(proof).some((key) => !["role", "path", "sha256"].includes(key))
          || !["creation_record", "assignment", "license", "employment_record", "commission_agreement", "public_domain_record", "conflict_evidence"].includes(proof.role)
          || !validSha(proof.sha256)) throw new InputError("copyright proof reference is invalid", "VERIFICATION_ARTIFACT_INVALID");
        const proofPath = safeBoundArtifactPath(taskDir, proof.path, /^raw\/copyright-provenance\/.+/, "VERIFICATION_ARTIFACT_INVALID");
        if (!existsSync(proofPath) || sha256(readFileSync(proofPath)) !== proof.sha256) {
          throw new InputError(`copyright proof is missing or stale: ${proof.path}`, "VERIFICATION_ARTIFACT_INVALID");
        }
      }
    } else if (event.schema_version !== "2.0" || event.official_record_verified !== true
      || Object.keys(event).some((key) => !["schema_version", "verification_id", "task_id", "candidate_id", "authority_tier", "official_record_verified", "official_status", "authorization_status", "right_identity", "enforcement_identity", "evidence_refs", "source_locator", "verified_by", "verified_at", "digest"].includes(key))
      || !HIGH_AUTHORITY.has(event.authority_tier)
      || !["active", "pending", "expired", "cancelled", "abandoned", "rejected", "disputed", "not_found"].includes(event.official_status)
      || !["authorized", "unlicensed", "unknown", "not_applicable"].includes(event.authorization_status)
      || !event.right_identity || !MODULES.includes(event.right_identity.module)
      || Object.keys(event.right_identity).some((key) => !["module", "jurisdiction", "record_number"].includes(key))
      || event.right_identity.jurisdiction !== "US"
      || (event.right_identity.record_number !== null && typeof event.right_identity.record_number !== "string")
      || !validRefList(event.evidence_refs, { nonEmpty: true })
      || event.evidence_refs.some((ref) => !evidenceById.has(ref))
      || typeof event.source_locator !== "string" || event.source_locator.length === 0
      || !event.verified_by || !["agent", "human", "backend", "reviewer"].includes(event.verified_by.type)
      || typeof event.verified_by.id !== "string" || event.verified_by.id.length === 0
      || typeof event.verified_by.session_id !== "string" || event.verified_by.session_id.length === 0
      || !validDateTime(event.verified_at) || !validSha(event.digest)
      || event.digest !== immutableArtifactDigest(event)) {
      throw new InputError(`official verification contract is incomplete: ${verification.verification_id}`, "VERIFICATION_ARTIFACT_INVALID");
    }
    if (!copyright && event.right_identity.module === "enforcement_public_signals") {
      const identity = event.enforcement_identity;
      if (!identity || Object.keys(identity).some((key) => !["claimant", "case_or_complaint_id", "procedure_status", "target_product_digest", "underlying_candidate_ids"].includes(key))
        || typeof identity.claimant !== "string" || identity.claimant.length === 0
        || typeof identity.case_or_complaint_id !== "string" || identity.case_or_complaint_id.length === 0
        || !["active_tro", "active_injunction", "active_litigation", "active_complaint", "platform_enforcement", "closed", "dismissed"].includes(identity.procedure_status)
        || !validSha(identity.target_product_digest)
        || !validRefList(identity.underlying_candidate_ids, { nonEmpty: true })) {
        throw new InputError(`enforcement verification identity is incomplete: ${verification.verification_id}`, "VERIFICATION_ARTIFACT_INVALID");
      }
    } else if (!copyright && event.enforcement_identity !== undefined) {
      throw new InputError(`non-enforcement verification contains enforcement identity: ${verification.verification_id}`, "VERIFICATION_ARTIFACT_INVALID");
    }
    verificationById.set(verification.verification_id, { ...verification, event, copyright });
  };
  for (const verification of ledger.official_verifications) registerVerification(verification, false);
  for (const verification of ledger.copyright_provenance_verifications) registerVerification(verification, true);
  return { evidenceById, ledgerCandidateById, verificationById, runById, queryPlan, product };
}

function validateFormalCoverageCheckpoint(taskDir, taskId, ledger, runById, queryPlan) {
  const coveragePath = join(taskDir, "checkpoints", "coverage.json");
  if (!existsSync(coveragePath)) {
    throw new InputError("formal release requires the frozen discovery coverage checkpoint", "FORMAL_COVERAGE_CHECKPOINT_REQUIRED");
  }
  const coverage = readJson(coveragePath, "discovery coverage checkpoint");
  const requiredRows = array(coverage.rows).filter((row) => row?.required === true);
  const plannedRequired = array(queryPlan.items).filter((item) => item?.required === true);
  const plannedIds = new Set(plannedRequired.map((item) => item.query_id));
  const rowIds = new Set(requiredRows.map((row) => row.query_id));
  const coveredModules = new Set(requiredRows.map((row) => row.module));
  if (coverage.schema_version !== "0.1" || coverage.task_id !== taskId
    || coverage.query_plan_digest !== ledger.query_plan_digest || coverage.evidence_digest !== ledger.digest
    || coverage.status !== "complete" || coverage.assessment_ready !== true
    || !Number.isInteger(coverage.required_total) || coverage.required_total < LEGACY_DISCOVERY_MODULES.length
    || coverage.completed_total !== coverage.required_total
    || requiredRows.length !== coverage.required_total
    || !Array.isArray(coverage.gap_query_ids) || coverage.gap_query_ids.length !== 0
    || !validDateTime(coverage.evaluated_at) || !validSha(coverage.digest)
    || plannedIds.size !== requiredRows.length
    || [...plannedIds].some((queryId) => !rowIds.has(queryId))
    || LEGACY_DISCOVERY_MODULES.some((module) => !coveredModules.has(module))) {
    throw new InputError("discovery coverage checkpoint is incomplete or not bound to the frozen evidence", "FORMAL_COVERAGE_CHECKPOINT_INVALID");
  }
  for (const row of requiredRows) {
    if (!row || !plannedIds.has(row.query_id) || !LEGACY_DISCOVERY_MODULES.includes(row.module)
      || row.target_jurisdiction !== "US" || row.provider_jurisdiction !== "US"
      || row.coverage_status !== "complete" || row.reason_code !== "QUERY_COMPLETED"
      || !validRefList(row.matching_run_ids, { nonEmpty: true })) {
      throw new InputError(`coverage row is invalid: ${row?.query_id ?? "unknown"}`, "FORMAL_COVERAGE_CHECKPOINT_INVALID");
    }
    const planned = plannedRequired.find((item) => item.query_id === row.query_id);
    if (!planned || planned.module !== row.module) {
      throw new InputError(`coverage row does not match the query plan: ${row.query_id}`, "FORMAL_COVERAGE_CHECKPOINT_INVALID");
    }
    for (const runId of row.matching_run_ids) {
      const run = runById.get(runId);
      if (!run || run.query_id !== row.query_id || !run.result.coverage_modules.includes(row.module)
        || !["success", "no_result"].includes(run.result.status)) {
        throw new InputError(`coverage row does not bind a completed provider run: ${row.query_id}`, "FORMAL_COVERAGE_CHECKPOINT_INVALID");
      }
    }
  }
}

function recordVerification(taskDir, inputPath, kind) {
  if (!["official", "copyright"].includes(kind)) {
    throw new InputError("--kind must be official or copyright", "VERIFICATION_KIND_INVALID");
  }
  const ledgerPath = join(taskDir, "05_evidence_ledger.json");
  const coveragePath = join(taskDir, "checkpoints", "coverage.json");
  if (!existsSync(ledgerPath) || !existsSync(coveragePath)) {
    throw new InputError("verification ingestion requires frozen evidence and coverage artifacts", "VERIFICATION_INGESTION_NOT_READY");
  }
  const oldLedgerText = readFileSync(ledgerPath, "utf8");
  const oldCoverageText = readFileSync(coveragePath, "utf8");
  const sourceManifestPath = join(taskDir, SOURCE_MANIFEST_RELATIVE_PATH);
  const oldSourceManifestText = existsSync(sourceManifestPath) ? readFileSync(sourceManifestPath, "utf8") : null;
  const oldLedger = JSON.parse(oldLedgerText);
  const validated = validateFrozenEvidenceLedger(taskDir, oldLedger, oldLedger.task_id);
  validateFormalCoverageCheckpoint(taskDir, oldLedger.task_id, oldLedger, validated.runById, validated.queryPlan);
  const oldSourceManifest = validateSourceManifest(taskDir, oldLedger.task_id, validated.product, oldLedger);

  const supplied = readJson(inputPath, `${kind} verification input`);
  const event = { ...supplied };
  if (Object.hasOwn(event, "digest") && event.digest !== immutableArtifactDigest(event)) {
    throw new InputError("verification input digest mismatch", "VERIFICATION_ARTIFACT_INVALID");
  }
  event.digest = immutableArtifactDigest(event);
  const copyright = kind === "copyright";
  const idPattern = copyright ? /^CPV-[a-f0-9]{24}$/ : /^V-[A-Za-z0-9_-]{4,100}$/;
  if (!idPattern.test(event.verification_id ?? "") || !validated.ledgerCandidateById.has(event.candidate_id)) {
    throw new InputError("verification does not identify a frozen ledger candidate", "VERIFICATION_ARTIFACT_INVALID");
  }
  if (copyright && event.evidence_revision !== oldLedger.revision) {
    throw new InputError("copyright verification does not bind the current evidence revision", "VERIFICATION_EVIDENCE_REVISION_MISMATCH");
  }
  const collectionKey = copyright ? "copyright_provenance_verifications" : "official_verifications";
  const relativeDirectory = copyright
    ? "normalized/copyright-provenance-verifications"
    : "normalized/official-verifications";
  const finalRelativePath = `${relativeDirectory}/${event.verification_id}.json`;
  const finalPath = join(taskDir, finalRelativePath);
  const stagingRelativePath = `${relativeDirectory}/${event.verification_id}.staging-${process.pid}.json`;
  const stagingPath = join(taskDir, stagingRelativePath);
  const eventContent = `${JSON.stringify(event, null, 2)}\n`;
  const eventSha = sha256(eventContent);
  const existingEntry = array(oldLedger[collectionKey]).find((item) => item.verification_id === event.verification_id);
  if (existingEntry) {
    const existingEventPath = safeBoundArtifactPath(
      taskDir,
      existingEntry.event_path,
      copyright
        ? /^normalized\/copyright-provenance-verifications\/[A-Za-z0-9][A-Za-z0-9_.-]*\.json$/
        : /^normalized\/official-verifications\/[A-Za-z0-9][A-Za-z0-9_.-]*\.json$/,
      "VERIFICATION_ARTIFACT_INVALID",
    );
    const existingEvent = readJson(existingEventPath, "existing verification event");
    if (existingEntry.candidate_id !== event.candidate_id || !sameJson(existingEvent, event)) {
      throw new InputError("verification id already exists with different content", "VERIFICATION_ID_CONFLICT");
    }
    return {
      status: "already_registered",
      reason_code: "VERIFICATION_ALREADY_REGISTERED",
      verification_id: event.verification_id,
      evidence_revision: oldLedger.revision,
      assessment_rebuild_required: true,
    };
  }
  mkdirSync(dirname(stagingPath), { recursive: true });
  let finalCreated = false;
  try {
    writeFileSync(stagingPath, eventContent);
    const entry = {
      verification_id: event.verification_id,
      candidate_id: event.candidate_id,
      event_path: stagingRelativePath,
      event_sha256: eventSha,
    };
    const stagedLedger = JSON.parse(JSON.stringify(oldLedger));
    stagedLedger[collectionKey].push(entry);
    validateFrozenEvidenceLedger(taskDir, stagedLedger, oldLedger.task_id);

    if (existsSync(finalPath)) {
      if (readFileSync(finalPath, "utf8") !== eventContent) {
        throw new InputError("verification destination already contains different content", "VERIFICATION_ID_CONFLICT");
      }
      unlinkSync(stagingPath);
    } else {
      renameSync(stagingPath, finalPath);
      finalCreated = true;
    }

    const recordedAt = now();
    const newLedger = JSON.parse(JSON.stringify(oldLedger));
    newLedger.revision += 1;
    newLedger.parent_digest = oldLedger.digest;
    newLedger.updated_at = recordedAt;
    newLedger.frozen = true;
    newLedger.frozen_at = recordedAt;
    newLedger[collectionKey].push({ ...entry, event_path: finalRelativePath });
    newLedger.digest = immutableArtifactDigest(newLedger);
    validateFrozenEvidenceLedger(taskDir, newLedger, oldLedger.task_id);

    const newCoverage = JSON.parse(oldCoverageText);
    newCoverage.evidence_digest = newLedger.digest;
    newCoverage.evaluated_at = recordedAt;
    newCoverage.digest = immutableArtifactDigest(newCoverage);
    writeFileSync(ledgerPath, `${JSON.stringify(newLedger, null, 2)}\n`);
    writeFileSync(coveragePath, `${JSON.stringify(newCoverage, null, 2)}\n`);
    const rebound = validateFrozenEvidenceLedger(taskDir, newLedger, oldLedger.task_id);
    validateFormalCoverageCheckpoint(taskDir, oldLedger.task_id, newLedger, rebound.runById, rebound.queryPlan);
    writeSourceManifest(taskDir, oldLedger.task_id, rebound.product, newLedger, {
      revision: oldSourceManifest.revision + 1,
      parentDigest: oldSourceManifest.digest,
      sealedAt: recordedAt,
    });
    return {
      status: "recorded",
      reason_code: "VERIFICATION_RECORDED",
      verification_id: event.verification_id,
      evidence_revision: newLedger.revision,
      evidence_digest: newLedger.digest,
      event_path: finalRelativePath,
      assessment_rebuild_required: true,
    };
  } catch (error) {
    writeFileSync(ledgerPath, oldLedgerText);
    writeFileSync(coveragePath, oldCoverageText);
    if (oldSourceManifestText === null) {
      if (existsSync(sourceManifestPath)) unlinkSync(sourceManifestPath);
    } else {
      writeFileSync(sourceManifestPath, oldSourceManifestText);
    }
    if (existsSync(stagingPath)) unlinkSync(stagingPath);
    if (finalCreated && existsSync(finalPath)) unlinkSync(finalPath);
    throw error;
  }
}

function validateFormalSourceEvidence(taskDir, assessmentInput, assessment) {
  const highDriverIds = new Set(assessment.modules
    .filter((module) => ["high", "critical"].includes(module.legal_risk))
    .flatMap((module) => module.risk_driver_candidate_ids));
  if (!assessment.overall.formal_conclusion_allowed) return;
  const formalEvidenceCandidateIds = new Set(assessmentInput.candidates
    .filter(isRatingRelevantCandidate)
    .map((candidate) => candidate.candidate_id));
  const highRelease = highDriverIds.size > 0;
  const ledgerPath = join(taskDir, "05_evidence_ledger.json");
  if (!existsSync(ledgerPath)) {
    throw new InputError(
      "formal release requires a frozen evidence ledger",
      highRelease ? "HIGH_SOURCE_LEDGER_REQUIRED" : "FORMAL_SOURCE_LEDGER_REQUIRED",
    );
  }
  const ledger = readJson(ledgerPath, "frozen evidence ledger");
  const { evidenceById, ledgerCandidateById, verificationById, runById, queryPlan, product } = validateFrozenEvidenceLedger(taskDir, ledger, assessment.task_id);
  validateFormalCoverageCheckpoint(taskDir, assessment.task_id, ledger, runById, queryPlan);
  validateSourceManifest(taskDir, assessment.task_id, product, ledger);
  const copyrightVeryLow = assessment.modules.some((module) => (
    module.module === "copyright_creative_ip" && module.legal_risk === "very_low"
  ));
  if (copyrightVeryLow || assessment.overall.legal_risk === "very_low" || assessment.overall.operational_action === "proceed") {
    validateCompleteCreativeProvenance(taskDir, product, evidenceById);
  }

  for (const ref of array(assessmentInput.review?.review_refs)) {
    const review = readJson(join(taskDir, ref.path), `${ref.round} review artifact`);
    for (const observation of array(review.modules).flatMap((module) => array(module.fact_observations))) {
      if (array(observation.evidence_refs).some((item) => !evidenceById.has(item))
        || array(observation.verification_refs).some((item) => !verificationById.has(item))) {
        throw new InputError("review observations cite evidence outside the frozen ledger", "REVIEW_EVIDENCE_REFERENCE_INVALID");
      }
    }
  }
  if (assessmentInput.review?.resolution_ref) {
    const resolution = readJson(join(taskDir, assessmentInput.review.resolution_ref.path), "resolution artifact");
    for (const fact of array(resolution.resolved_facts)) {
      if (array(fact.evidence_refs).some((item) => !evidenceById.has(item))) {
        throw new InputError("resolution cites evidence outside the frozen ledger", "RESOLUTION_EVIDENCE_REFERENCE_INVALID");
      }
    }
  }

  const candidateById = new Map(assessment.candidate_summaries.map((candidate) => [candidate.candidate_id, candidate]));
  const lineageIds = (candidate) => {
    const ids = new Set();
    let cursor = candidate;
    while (cursor && !ids.has(cursor.candidate_id)) {
      ids.add(cursor.candidate_id);
      cursor = cursor.duplicate_of ? candidateById.get(cursor.duplicate_of) : null;
    }
    return ids;
  };
  const assessmentCandidateIds = new Set(assessmentInput.candidates.map((candidate) => candidate.candidate_id));
  const omittedLedgerCandidateIds = [...ledgerCandidateById.keys()].filter((candidateId) => !assessmentCandidateIds.has(candidateId));
  if (omittedLedgerCandidateIds.length > 0) {
    throw new InputError(
      `assessment omits frozen ledger candidates: ${omittedLedgerCandidateIds.join(", ")}`,
      "CANDIDATE_COVERAGE_MISMATCH",
    );
  }
  for (const candidate of assessmentInput.candidates) {
    const lineage = lineageIds(candidate);
    const ledgerCandidate = [...lineage].map((id) => ledgerCandidateById.get(id)).find(Boolean);
    if (!ledgerCandidate) {
      throw new InputError(`${candidate.candidate_id} is not linked to a frozen ledger candidate`, "CANDIDATE_COVERAGE_MISMATCH");
    }
    const frozenEvidence = new Set(ledgerCandidate.evidence_refs);
    if (candidate.evidence_refs.some((ref) => !frozenEvidence.has(ref))) {
      throw new InputError(`${candidate.candidate_id} has evidence outside its frozen ledger lineage`, "HIGH_EVIDENCE_REFERENCE_INVALID");
    }
    if (candidate.candidate_id === ledgerCandidate.candidate_id
      && ledgerCandidate.evidence_refs.some((ref) => !candidate.evidence_refs.includes(ref))) {
      throw new InputError(`${candidate.candidate_id} drops frozen ledger evidence`, "CANDIDATE_COVERAGE_MISMATCH");
    }
    if (candidate.candidate_id === ledgerCandidate.candidate_id) {
      const frozenDisposition = ledgerCandidate.disposition?.value ?? ledgerCandidate.disposition;
      if (["material", "needs_review", "not_material"].includes(frozenDisposition)) {
        const migratedMateriality = frozenDisposition === "not_material" ? "not_material" : "unresolved";
        if (candidate.legacy_disposition !== frozenDisposition
          || typeof candidate.legacy_reassessed !== "boolean"
          || (candidate.legacy_reassessed !== true && candidate.legal_materiality !== migratedMateriality)) {
          throw new InputError(
            `${candidate.candidate_id} is not bound to its frozen legacy reassessment state`,
            "LEGACY_REASSESSMENT_REQUIRED",
          );
        }
      }
      const frozenVerificationIds = [...verificationById.values()]
        .filter((verification) => verification.candidate_id === ledgerCandidate.candidate_id)
        .map((verification) => verification.verification_id);
      if (frozenVerificationIds.some((verificationId) => !candidate.verification_refs.includes(verificationId))) {
        throw new InputError(
          `${candidate.candidate_id} omits a frozen verification event`,
          "HIGH_VERIFICATION_REFERENCE_INVALID",
        );
      }
    }
    if (candidate.verification_refs.some((ref) => {
      const verification = verificationById.get(ref);
      return !verification || !lineage.has(verification.candidate_id);
    })) {
      throw new InputError(`${candidate.candidate_id} has a missing or incorrectly linked verification`, "HIGH_VERIFICATION_REFERENCE_INVALID");
    }
  }
  for (const candidateId of formalEvidenceCandidateIds) {
    const candidate = candidateById.get(candidateId);
    if (!candidate) throw new InputError(`missing high-risk candidate ${candidateId}`, "HIGH_EVIDENCE_GATE_NOT_MET");
    const lineage = lineageIds(candidate);
    const ledgerCandidate = [...lineage].map((id) => ledgerCandidateById.get(id)).find(Boolean);
    if (!ledgerCandidate) {
      throw new InputError(`${candidateId} is not linked to a frozen ledger candidate`, "HIGH_EVIDENCE_REFERENCE_INVALID");
    }
    const moduleMatches = (module) => module === candidate.module
      || (module === "figurative_trade_dress" && ["figurative_mark", "trade_dress"].includes(candidate.module));
    if (!moduleMatches(ledgerCandidate.module) || ledgerCandidate.jurisdiction !== "US"
      || (["right_record", "application", "enforcement_event"].includes(candidate.record_kind)
        && (typeof candidate.record_number !== "string" || candidate.record_number.length === 0
          || ledgerCandidate.record_number !== candidate.record_number))) {
      throw new InputError(`${candidateId} does not match the frozen right identity`, "HIGH_EVIDENCE_RIGHT_IDENTITY_MISMATCH");
    }
    if (candidate.module === "enforcement_public_signals"
      && (factor(candidate, "case_or_complaint_id", null) !== candidate.record_number
        || typeof ledgerCandidate.owner !== "string" || ledgerCandidate.owner.length === 0
        || ledgerCandidate.owner !== factor(candidate, "claimant", null))) {
      throw new InputError(`${candidateId} does not match the frozen enforcement identity`, "HIGH_EVIDENCE_RIGHT_IDENTITY_MISMATCH");
    }
    const ledgerCandidateEvidence = new Set(ledgerCandidate.evidence_refs);
    const ledgerEvidenceRefs = array(candidate.evidence_refs).filter((ref) => evidenceById.has(ref) && ledgerCandidateEvidence.has(ref));
    if (ledgerEvidenceRefs.length === 0
      || array(candidate.evidence_refs).some((ref) => (
        !evidenceById.has(ref) || !ledgerCandidateEvidence.has(ref)
      ))) {
      throw new InputError(`${candidateId} has missing or dangling evidence references`, "HIGH_EVIDENCE_REFERENCE_INVALID");
    }
    const ledgerVerificationRefs = array(candidate.verification_refs).filter((ref) => {
      const verification = verificationById.get(ref);
      return verification && lineage.has(verification.candidate_id);
    });
    if (ledgerVerificationRefs.length !== array(candidate.verification_refs).length) {
      throw new InputError(`${candidateId} has a missing or incorrectly linked verification`, "HIGH_VERIFICATION_REFERENCE_INVALID");
    }
    for (const ref of ledgerVerificationRefs) {
      const verification = verificationById.get(ref);
      const event = verification.event;
      if (candidate.module === "copyright_creative_ip") {
        if (!verification.copyright || event.candidate_key !== ledgerCandidate.candidate_key) {
          throw new InputError(`${candidateId} has a mismatched copyright verification`, "HIGH_VERIFICATION_REFERENCE_INVALID");
        }
      } else if (verification.copyright || !moduleMatches(event.right_identity.module)
        || event.right_identity.record_number !== candidate.record_number
        || event.evidence_refs.some((evidenceRef) => !ledgerCandidateEvidence.has(evidenceRef))) {
        throw new InputError(`${candidateId} has a mismatched official verification`, "HIGH_VERIFICATION_REFERENCE_INVALID");
      }
      if (candidate.module === "enforcement_public_signals") {
        const identity = event.enforcement_identity;
        const expectedUnderlyingIds = [...array(factor(candidate, "underlying_risk_driver_ids", []))].sort();
        if (!identity || identity.claimant !== factor(candidate, "claimant", null)
          || identity.case_or_complaint_id !== factor(candidate, "case_or_complaint_id", null)
          || identity.procedure_status !== factor(candidate, "procedure_status", null)
          || identity.target_product_digest !== product.digest
          || !sameJson([...identity.underlying_candidate_ids].sort(), expectedUnderlyingIds)) {
          throw new InputError(`${candidateId} is not bound to the verified enforcement target and procedure`, "HIGH_VERIFICATION_REFERENCE_INVALID");
        }
      }
    }
    const officialStatus = factor(candidate, "right_status", null);
    const officialVerified = factor(candidate, "official_record_verified", false) === true;
    if (candidate.module !== "copyright_creative_ip" && Object.hasOwn(candidate.factors, "right_status")) {
      const officialEvents = ledgerVerificationRefs
        .map((ref) => verificationById.get(ref))
        .filter((verification) => !verification.copyright)
        .map((verification) => verification.event);
      if ((officialVerified && officialEvents.length === 0)
        || (officialEvents.length > 0 && !officialVerified)
        || (ledgerVerificationRefs.length > 0
          && !officialEvents.some((event) => event.official_status === officialStatus))) {
        throw new InputError(`${candidateId} lacks a verification matching its official status`, "HIGH_VERIFICATION_REFERENCE_INVALID");
      }
    }
    const authorization = factor(candidate, "authorization_status", null);
    if (candidate.module !== "copyright_creative_ip") {
      const verifiedAuthorizations = new Set(ledgerVerificationRefs
        .map((ref) => verificationById.get(ref))
        .filter((verification) => !verification.copyright)
        .map((verification) => verification.event.authorization_status)
        .filter((value) => ["authorized", "unlicensed"].includes(value)));
      if (verifiedAuthorizations.size > 1
        || (verifiedAuthorizations.size === 1 && !verifiedAuthorizations.has(authorization))
        || (["authorized", "unlicensed"].includes(authorization) && !verifiedAuthorizations.has(authorization))) {
        throw new InputError(`${candidateId} lacks a verification matching its authorization status`, "HIGH_VERIFICATION_REFERENCE_INVALID");
      }
    }
    if (candidate.module === "copyright_creative_ip") {
      const commercialUseCovered = factor(candidate, "commercial_use_covered", "unknown");
      const provenanceEvents = ledgerVerificationRefs
        .map((ref) => verificationById.get(ref))
        .filter((verification) => verification.copyright)
        .map((verification) => verification.event);
      const verifiedAuthorizationStates = new Set(provenanceEvents.map((event) => (
        ["owned", "licensed"].includes(event.resolution) ? "authorized" : event.resolution
      )).filter((value) => ["authorized", "unlicensed"].includes(value)));
      const matchingProvenance = authorization === "authorized"
        ? provenanceEvents.some((event) => ["owned", "licensed"].includes(event.resolution)
          && event.commercial_use_allowed === true
          && event.amazon_use_allowed === true
          && commercialUseCovered === true)
        : authorization === "unlicensed"
          ? provenanceEvents.some((event) => event.resolution === "unlicensed"
            && event.commercial_use_allowed === false
            && commercialUseCovered === false)
          : verifiedAuthorizationStates.size === 0;
      if (verifiedAuthorizationStates.size > 1 || !matchingProvenance) {
        throw new InputError(`${candidateId} lacks a copyright provenance event matching its authorization`, "HIGH_VERIFICATION_REFERENCE_INVALID");
      }
    }
    if (!highDriverIds.has(candidateId)) continue;
    if (ledgerVerificationRefs.length === 0) {
      throw new InputError(`${candidateId} lacks a bound official verification`, "HIGH_VERIFICATION_REFERENCE_INVALID");
    }
    for (const ref of ledgerVerificationRefs) {
      const verification = verificationById.get(ref);
      if (candidate.module === "copyright_creative_ip"
        && (!verification.copyright || verification.event.resolution !== "unlicensed"
          || verification.event.commercial_use_allowed !== false
          || verification.event.candidate_key !== ledgerCandidate.candidate_key
          || typeof candidate.owner !== "string" || candidate.owner.length === 0
          || ledgerCandidate.owner !== candidate.owner
          || verification.event.rights_owner !== candidate.owner
          || !ledgerCandidate.evidence_refs.some((evidenceRef) => (
            evidenceById.get(evidenceRef)?.raw_refs.includes(verification.event.asset_ref)
          ))
          || (factor(candidate, "creator_or_earliest_source", null)
            && verification.event.creator !== factor(candidate, "creator_or_earliest_source", null)))) {
        throw new InputError(`${candidateId} lacks an unlicensed copyright provenance verification`, "HIGH_VERIFICATION_REFERENCE_INVALID");
      }
      if (candidate.module !== "copyright_creative_ip"
        && (verification.copyright || verification.event.official_status !== "active"
          || !moduleMatches(verification.event.right_identity.module)
          || verification.event.right_identity.record_number !== candidate.record_number)) {
        throw new InputError(`${candidateId} lacks an active official verification`, "HIGH_VERIFICATION_REFERENCE_INVALID");
      }
    }
    if (candidate.module !== "copyright_creative_ip"
      && factor(candidate, "authorization_status", "unknown") === "unlicensed"
      && !ledgerVerificationRefs.some((ref) => verificationById.get(ref).event.authorization_status === "unlicensed")) {
      throw new InputError(`${candidateId} lacks a bound unlicensed-use verification`, "HIGH_VERIFICATION_REFERENCE_INVALID");
    }
  }
}

function validateRelease(taskDir) {
  const reportDir = join(taskDir, "report-v2");
  const manifest = readJson(join(reportDir, "manifest.json"), "v2 report manifest");
  const report = readJson(join(reportDir, "report_data.json"), "v2 report data");
  const assessment = readJson(join(taskDir, "v2", "assessment.json"), "v2 assessment");
  const decisionTrace = readJson(join(taskDir, "v2", "decision-trace.json"), "v2 decision trace");
  const coverage = readJson(join(taskDir, "v2", "coverage.json"), "v2 coverage");
  const assessmentInput = readJson(join(taskDir, "v2", "assessment-input.snapshot.json"), "assessment input snapshot");
  validateAssessmentInput(assessmentInput);
  validateReviewArtifactBindings(taskDir, assessmentInput, assessment);
  validateFormalSourceEvidence(taskDir, assessmentInput, assessment);
  const rulesDigest = rulesFingerprint();
  const { manifest_digest: manifestDigest, ...manifestBase } = manifest;
  if (manifestDigest !== sha256(manifestBase)) {
    throw new InputError("manifest digest mismatch", "MANIFEST_DIGEST_MISMATCH");
  }
  for (const artifact of array(manifest.artifacts)) {
    const path = join(reportDir, artifact.name);
    if (!existsSync(path)) throw new InputError(`missing report artifact: ${artifact.name}`, "ARTIFACT_MISSING");
    const content = readFileSync(path);
    if (sha256(content) !== artifact.sha256 || statSync(path).size !== artifact.bytes) {
      throw new InputError(`artifact digest mismatch: ${artifact.name}`, "ARTIFACT_DIGEST_MISMATCH");
    }
  }
  const requiredArtifacts = new Set(["report_data.json", "ipr-risk-screening-report.html", "ipr-risk-screening-report.md"]);
  const manifestArtifacts = new Set(array(manifest.artifacts).map((artifact) => artifact.name));
  if (requiredArtifacts.size !== manifestArtifacts.size || [...requiredArtifacts].some((name) => !manifestArtifacts.has(name))) {
    throw new InputError("manifest artifact set is incomplete", "MANIFEST_ARTIFACT_SET_INVALID");
  }
  const { digest: reportDigest, ...reportBase } = report;
  if (reportDigest !== sha256(reportBase)) throw new InputError("report data digest mismatch", "REPORT_DATA_DIGEST_MISMATCH");
  const { digest: assessmentDigest, ...assessmentBase } = assessment;
  if (assessmentDigest !== sha256(assessmentBase)) throw new InputError("assessment digest mismatch", "ASSESSMENT_DIGEST_MISMATCH");
  const inputDigest = sha256(assessmentInput);
  const sharedTaskId = assessment.task_id;
  if ([manifest.task_id, report.task_id, decisionTrace.task_id, coverage.task_id, assessmentInput.task_id].some((taskId) => taskId !== sharedTaskId)) {
    throw new InputError("task id mismatch across v2 artifacts", "ARTIFACT_TASK_MISMATCH");
  }
  if ([manifest.ruleset_version, report.ruleset_version, assessment.ruleset_version, decisionTrace.ruleset_version, coverage.ruleset_version, assessmentInput.ruleset_version].some((version) => version !== RULESET_VERSION)) {
    throw new InputError("ruleset version mismatch across v2 artifacts", "RULESET_VERSION_MISMATCH");
  }
  if (manifest.rules_digest !== rulesDigest || decisionTrace.rules_digest !== rulesDigest) {
    throw new InputError("rules digest mismatch", "RULES_DIGEST_MISMATCH");
  }
  if (manifest.report_mode !== report.report_mode
    || manifest.formal_conclusion_allowed !== report.overview.formal_conclusion_allowed) {
    throw new InputError("manifest status does not match report data", "REPORT_MANIFEST_BINDING_MISMATCH");
  }
  if (manifest.assessment_digest !== assessmentDigest
    || report.trace.assessment_digest !== assessmentDigest
    || decisionTrace.assessment_digest !== assessmentDigest) {
    throw new InputError("stale report or decision trace", "ASSESSMENT_BINDING_MISMATCH");
  }
  if (coverage.assessment_input_digest !== inputDigest || decisionTrace.assessment_input_digest !== inputDigest) {
    throw new InputError("assessment input digest mismatch", "ASSESSMENT_INPUT_BINDING_MISMATCH");
  }
  const {
    schema_version: _coverageSchema,
    ruleset_version: _coverageRules,
    task_id: _coverageTask,
    assessment_input_digest: _coverageInputDigest,
    ...coveragePayload
  } = coverage;
  if (!sameJson(coveragePayload, assessmentInput.coverage)) {
    throw new InputError("coverage artifact does not match the assessment input", "COVERAGE_BINDING_MISMATCH");
  }
  for (const [key, value] of Object.entries(assessment.decision_trace)) {
    if (!sameJson(decisionTrace[key], value)) {
      throw new InputError(`decision trace mismatch at ${key}`, "DECISION_TRACE_BINDING_MISMATCH");
    }
  }
  if (decisionTrace.candidate_digest !== sha256(assessment.candidate_summaries)
    || decisionTrace.operational_action !== assessment.overall.operational_action
    || !sameJson(decisionTrace.risk_driver_candidate_ids, assessment.modules.flatMap((module) => module.risk_driver_candidate_ids))) {
    throw new InputError("decision trace summary is stale", "DECISION_TRACE_BINDING_MISMATCH");
  }
  const productPath = join(taskDir, "02_product_facts.json");
  const queryPlanPath = join(taskDir, "04_query_plan.json");
  const evidencePath = join(taskDir, "05_evidence_ledger.json");
  const sourceManifestPath = join(taskDir, SOURCE_MANIFEST_RELATIVE_PATH);
  const currentProductDigest = digestFileOrFallback(productPath, { task_id: sharedTaskId, artifact: "product_facts", missing: true });
  const currentQueryDigest = digestFileOrFallback(queryPlanPath, { task_id: sharedTaskId, artifact: "query_plan", missing: true });
  const currentEvidenceDigest = digestFileOrFallback(evidencePath, assessment.candidate_summaries);
  const currentSourceManifestDigest = existsSync(sourceManifestPath) ? sha256(readFileSync(sourceManifestPath)) : null;
  if (decisionTrace.product_facts_digest !== currentProductDigest
    || decisionTrace.query_plan_digest !== currentQueryDigest
    || decisionTrace.evidence_digest !== currentEvidenceDigest
    || decisionTrace.source_manifest_digest !== currentSourceManifestDigest
    || report.trace.product_facts_digest !== currentProductDigest
    || report.trace.query_plan_digest !== currentQueryDigest
    || report.trace.evidence_digest !== currentEvidenceDigest
    || report.trace.source_manifest_digest !== currentSourceManifestDigest) {
    throw new InputError("source artifact digest mismatch", "SOURCE_ARTIFACT_BINDING_MISMATCH");
  }
  const reportDataArtifact = array(manifest.artifacts).find((artifact) => artifact.name === "report_data.json");
  if (!reportDataArtifact || manifest.report_data_digest !== reportDataArtifact.sha256) {
    throw new InputError("report data is not bound to the manifest", "REPORT_MANIFEST_BINDING_MISMATCH");
  }
  const comparableAssessment = JSON.parse(JSON.stringify(assessmentBase));
  const recalculated = evaluateAssessment(assessmentInput);
  comparableAssessment.decision_trace.evaluated_at = null;
  recalculated.decision_trace.evaluated_at = null;
  if (!sameJson(comparableAssessment, recalculated)) {
    throw new InputError("assessment no longer matches its inputs and rules", "ASSESSMENT_RECALCULATION_MISMATCH");
  }
  const expectedReport = reportData(taskDir, assessment);
  const comparableReport = JSON.parse(JSON.stringify(report));
  delete expectedReport.digest;
  delete comparableReport.digest;
  expectedReport.generated_at = null;
  comparableReport.generated_at = null;
  if (!sameJson(comparableReport, expectedReport)) {
    throw new InputError("report data does not match the current assessment and sources", "REPORT_RECALCULATION_MISMATCH");
  }
  validateCandidateCollection({ candidates: assessment.candidate_summaries });
  const candidateById = new Map(assessment.candidate_summaries.map((candidate) => [candidate.candidate_id, candidate]));
  for (const module of assessment.modules.filter((item) => ["high", "critical"].includes(item.legal_risk))) {
    if (module.risk_driver_candidate_ids.length === 0) throw new InputError(`${module.module} lacks a risk driver`, "HIGH_EVIDENCE_GATE_NOT_MET");
    for (const candidateId of module.risk_driver_candidate_ids) {
      const candidate = candidateById.get(candidateId);
      if (!candidate || candidate.legal_materiality !== "risk_bearing" || candidate.risk_driver_eligible !== true || !highEvidenceGate(candidate)) {
        throw new InputError(`${candidateId} fails the high-risk evidence gate`, "HIGH_EVIDENCE_GATE_NOT_MET");
      }
      const missingFactors = requiredRiskFactors(candidate.module).filter((key) => !Object.hasOwn(candidate.factors, key));
      if (missingFactors.length > 0) throw new InputError(`${candidateId} lacks complete module factors`, "HIGH_EVIDENCE_GATE_NOT_MET");
    }
  }
  if (readFileSync(join(reportDir, "ipr-risk-screening-report.html"), "utf8") !== renderHtml(report)
    || readFileSync(join(reportDir, "ipr-risk-screening-report.md"), "utf8") !== renderMarkdown(report)) {
    throw new InputError("rendered report is stale or was not derived from report_data.json", "REPORT_RENDER_BINDING_MISMATCH");
  }
  if (!report.overview.formal_conclusion_allowed || report.report_mode !== "formal") {
    throw new InputError("formal release is blocked; deliver only as draft/incomplete", "FORMAL_CONCLUSION_BLOCKED");
  }
  if (assessment.assessment_status !== "final" || !assessment.overall.formal_conclusion_allowed) {
    throw new InputError("assessment is not final", "FORMAL_CONCLUSION_BLOCKED");
  }
  return { status: "passed", reason_code: "V2_RELEASE_VALIDATED", report_directory: reportDir };
}

function rulesDescriptor() {
  if (rulesDescriptorCache) return rulesDescriptorCache;
  const path = join(skillDir, "references", "risk-rules.v2.json");
  if (existsSync(path)) {
    rulesDescriptorCache = readJson(path, "v2 risk rules");
    return rulesDescriptorCache;
  }
  rulesDescriptorCache = {
    ruleset_version: RULESET_VERSION,
    modules: MODULES,
    risk_order: RISK_ORDER,
    note: "Runtime fallback descriptor; packaged rule file is missing.",
  };
  return rulesDescriptorCache;
}

function executableRulesDigest() {
  return sha256(readFileSync(scriptPath));
}

function rulesFingerprint() {
  return sha256(canonicalize({
    descriptor_digest: sha256(canonicalize(rulesDescriptor())),
    executable_rules_digest: executableRulesDigest(),
  }));
}

function describedRules() {
  return {
    ...rulesDescriptor(),
    audit: {
      descriptor_digest: sha256(canonicalize(rulesDescriptor())),
      executable_rules_digest: executableRulesDigest(),
      rules_fingerprint: rulesFingerprint(),
      policy: "规则描述与可执行评级代码共同组成审计指纹；任一变化都会使旧报告发布校验失败。",
    },
  };
}

function requiredRiskFactors(module) {
  const definition = array(rulesDescriptor().modules).find((item) => item?.id === module);
  const configured = array(definition?.required_factors);
  return configured.length > 0 ? configured : FALLBACK_REQUIRED_RISK_FACTORS[module];
}

function print(value) {
  process.stdout.write(`${JSON.stringify(value, null, 2)}\n`);
}

function usage() {
  return `Usage:
  ipr-risk-v2.mjs version
  ipr-risk-v2.mjs rules describe [--json]
  ipr-risk-v2.mjs rules evaluate --input <assessment.json> [--dry-run] [--output <path>]
  ipr-risk-v2.mjs migrate-candidates --task-dir <task-dir>
  ipr-risk-v2.mjs validate-candidates --input <candidate-review.json>
  ipr-risk-v2.mjs prepare-assessment --task-dir <task-dir> --candidate-review <candidate-review.json>
  ipr-risk-v2.mjs record-verification --kind <official|copyright> --task-dir <task-dir> --input <verification.json>
  ipr-risk-v2.mjs merge-reviews --assessment-input <input.json> --first-review <review.json> --second-review <review.json> [--resolution <resolution.json>] [--output <path>]
  ipr-risk-v2.mjs finalize-assessment --task-dir <task-dir> --input <assessment-input.json>
  ipr-risk-v2.mjs render-report --task-dir <task-dir>
  ipr-risk-v2.mjs validate-release --task-dir <task-dir>`;
}

function main() {
  const { positional, options } = parseArgs(process.argv.slice(2));
  const command = positional[0];
  if (!command) throw new InputError(usage(), "COMMAND_REQUIRED");
  if (command === "version") {
    print({ name: "lc-ipr-risk-screening-v2", version: "2.0.0", ruleset_version: RULESET_VERSION, schema_version: SCHEMA_VERSION, rules_fingerprint: rulesFingerprint() });
    return;
  }
  if (command === "rules" && positional[1] === "describe") {
    print(describedRules());
    return;
  }
  if (command === "rules" && positional[1] === "evaluate") {
    if (!options.input) throw new InputError("--input is required", "ASSESSMENT_INPUT_REQUIRED");
    const result = evaluateAssessment(readJson(resolve(options.input), "assessment input"));
    if (options.output && !options["dry-run"]) writeJson(resolve(options.output), result);
    print(result);
    return;
  }
  if (command === "migrate-candidates") {
    if (!options["task-dir"]) throw new InputError("--task-dir is required", "TASK_DIR_REQUIRED");
    print(migrateCandidates(resolve(options["task-dir"])));
    return;
  }
  if (command === "validate-candidates") {
    if (!options.input) throw new InputError("--input is required", "CANDIDATE_INPUT_REQUIRED");
    print(validateCandidatesFile(resolve(options.input)));
    return;
  }
  if (command === "prepare-assessment") {
    if (!options["task-dir"] || !options["candidate-review"]) throw new InputError("--task-dir and --candidate-review are required", "ARGUMENT_REQUIRED");
    print(prepareAssessment(resolve(options["task-dir"]), resolve(options["candidate-review"])));
    return;
  }
  if (command === "record-verification") {
    if (!options["task-dir"] || !options.input || !options.kind) {
      throw new InputError("--task-dir, --input and --kind are required", "ARGUMENT_REQUIRED");
    }
    print(recordVerification(resolve(options["task-dir"]), resolve(options.input), options.kind));
    return;
  }
  if (command === "merge-reviews") {
    if (!options["assessment-input"] || !options["first-review"] || !options["second-review"]) {
      throw new InputError("--assessment-input, --first-review and --second-review are required", "ARGUMENT_REQUIRED");
    }
    print(mergeReviews(
      resolve(options["assessment-input"]),
      resolve(options["first-review"]),
      resolve(options["second-review"]),
      options.resolution ? resolve(options.resolution) : null,
      options.output ? resolve(options.output) : null,
    ));
    return;
  }
  if (command === "finalize-assessment") {
    if (!options["task-dir"] || !options.input) throw new InputError("--task-dir and --input are required", "ARGUMENT_REQUIRED");
    print(finalizeAssessment(resolve(options["task-dir"]), resolve(options.input)));
    return;
  }
  if (command === "render-report") {
    if (!options["task-dir"]) throw new InputError("--task-dir is required", "TASK_DIR_REQUIRED");
    print(renderReport(resolve(options["task-dir"])));
    return;
  }
  if (command === "validate-release") {
    if (!options["task-dir"]) throw new InputError("--task-dir is required", "TASK_DIR_REQUIRED");
    print(validateRelease(resolve(options["task-dir"])));
    return;
  }
  throw new InputError(`unknown command: ${positional.join(" ")}\n${usage()}`, "UNKNOWN_COMMAND");
}

try {
  main();
} catch (error) {
  const payload = {
    status: "error",
    reason_code: error instanceof InputError ? error.code : "UNEXPECTED_ERROR",
    message: error.message,
  };
  process.stderr.write(`${JSON.stringify(payload, null, 2)}\n`);
  process.exitCode = 2;
}
