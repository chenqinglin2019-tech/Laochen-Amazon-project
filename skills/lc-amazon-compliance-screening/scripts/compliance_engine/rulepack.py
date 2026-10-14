"""Load and verify a compiled rule pack (rulepack-*.json)."""
from __future__ import annotations

import json

from .common import KeywordMatcher, digest, excludes_of, flatten_keywords, norm_text


class RulePackError(ValueError):
    pass


class RulePack:
    def __init__(self, data: dict):
        if data.get("schema") != "compliance-rulepack-v1":
            raise RulePackError("规则包格式不对")
        content = data["content"]
        if digest(content) != data.get("digest"):
            raise RulePackError("规则包 digest 不一致，文件可能被改动")
        self.data = data
        self.version = data["version"]
        self.digest = data["digest"]
        self.taxonomy = content["taxonomy"]
        self.keywords = content["keywords"]
        self.sources = {s["id"]: s for s in content["sources"]}
        self.rules = {r["id"]: r for r in content["rules"]}
        self.families = self.taxonomy["families"]
        self.attributes = self.taxonomy["attributes"]
        self.claims = self.taxonomy["claims"]
        self.family_matchers = {fid: KeywordMatcher(flatten_keywords({k: v for k, v in spec.items() if k != "not"}))
                                for fid, spec in (self.keywords.get("families") or {}).items()}
        # Phrases removed from the text before matching a family ("wine glass" is not alcohol).
        self.family_excludes = {fid: [norm_text(x) for x in spec.get("not") or []]
                                for fid, spec in (self.keywords.get("families") or {}).items() if spec.get("not")}
        self.claim_matchers = {cid: KeywordMatcher(flatten_keywords(spec))
                               for cid, spec in (self.keywords.get("claims") or {}).items()}
        self.rule_matchers = {}
        for rid, rule in self.rules.items():
            kw = rule.get("keywords") or {}
            excl = excludes_of(kw) + excludes_of(kw.get("strong")) + excludes_of(kw.get("weak"))
            self.rule_matchers[rid] = (KeywordMatcher(flatten_keywords(kw.get("strong")), excl),
                                       KeywordMatcher(flatten_keywords(kw.get("weak")), excl))

    @classmethod
    def load(cls, path) -> "RulePack":
        with open(path, encoding="utf-8") as fh:
            return cls(json.load(fh))

    def rules_for(self, site: str):
        return [r for r in self.rules.values() if site in r["sites"] and r.get("status") != "retired"]

    def summary(self) -> dict:
        return {"version": self.version, "digest": self.digest, "rules": len(self.rules),
                "builtAt": self.data.get("builtAt")}
