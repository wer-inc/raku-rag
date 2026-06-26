#!/usr/bin/env python3
"""Unpack Kakuto LP standalone bundle into deployable index.html + assets/."""

from __future__ import annotations

import base64
import gzip
import json
import os
import re

SRC = os.path.join(os.path.dirname(__file__), "Kakuto LP (standalone).html")
OUT_DIR = os.path.dirname(__file__)
ASSETS_DIR = os.path.join(OUT_DIR, "assets")

CONFIG_JS = """// Kakuto LP — edit these values for your deployment.
window.KAKUTO_LP = {
  /** Scroll target or mailto for demo / PoC inquiries */
  demoCta: "#cta",
  /** Optional live product demo (e.g. http://localhost:3002/ after demo_up.sh) */
  liveDemoUrl: null,
  /** Contact email for 資料請求 form */
  contactEmail: "contact@kakuto.ai",
  /** Optional Calendly / booking URL (overrides demoCta for デモを予約 buttons) */
  calendlyUrl: null
};
"""


def main() -> None:
    with open(SRC, encoding="utf-8") as f:
        content = f.read()

    manifest = json.loads(
        re.search(r'<script type="__bundler/manifest">(.*?)</script>', content, re.DOTALL).group(1)
    )
    template_data = json.loads(
        re.search(r'<script type="__bundler/template">(.*?)</script>', content, re.DOTALL).group(1)
    )

    os.makedirs(ASSETS_DIR, exist_ok=True)

    for uuid, entry in manifest.items():
        data = base64.b64decode(entry["data"])
        if entry.get("compressed"):
            data = gzip.decompress(data)
        ext = ".woff2" if entry["mime"] == "font/woff2" else ".js"
        with open(os.path.join(ASSETS_DIR, uuid + ext), "wb") as f:
            f.write(data)

    page_html = template_data["pages"][template_data["entry"]]
    for uuid, entry in manifest.items():
        ext = ".woff2" if entry["mime"] == "font/woff2" else ".js"
        page_html = page_html.replace(uuid, f"assets/{uuid}{ext}")

    head_scripts = re.findall(r'<script[^>]*src="assets/[^"]+"[^>]*></script>', page_html)
    xdc_match = re.search(r"<x-dc>(.*?)</x-dc>", page_html, re.DOTALL)
    xdc_content = xdc_match.group(1) if xdc_match else ""
    after_xdc = page_html.split("</x-dc>")[-1] if "</x-dc>" in page_html else ""
    scripts = re.findall(r"<script[^>]*>.*?</script>", after_xdc, re.DOTALL)

    meta = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kakuto 確答AI — RAGに蓄積された知識から、設計書・見積もり・提案書を根拠つきで生成</title>
<meta name="description" content="Kakuto（確答AI）は、RAGに蓄積された既存仕様・過去案件・技術方針・制約から、設計書、見積もり、提案書、実装タスク、差分影響分析をcitationつきでドラフト生成するAIナレッジ基盤です。">
<meta property="og:title" content="Kakuto 確答AI — 設計書・見積もり・提案書を、根拠つきで生成。">
<meta property="og:description" content="RAGに蓄積された既存仕様・過去案件・技術方針から、外部提出前レビューを前提に成果物ドラフトを生成します。">
<meta property="og:type" content="website">
<meta name="theme-color" content="#5b5bd6">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='8' fill='%235b5bd6'/><rect x='10' y='10' width='12' height='12' rx='3' fill='white'/></svg>">
<script src="config.js"></script>
"""

    parts = [meta]
    parts.extend(head_scripts)
    parts.append(
        """
<style>
  html { scroll-behavior: smooth; }
</style>
</head>
<body>
<x-dc>"""
    )
    parts.append(xdc_content)
    parts.append("</x-dc>")
    parts.extend(scripts)
    parts.append(WIRE_SCRIPT)
    parts.append("</body></html>")

    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write("".join(parts))

    with open(os.path.join(OUT_DIR, "config.js"), "w", encoding="utf-8") as f:
        f.write(CONFIG_JS)

    asset_count = len(os.listdir(ASSETS_DIR))
    asset_bytes = sum(os.path.getsize(os.path.join(ASSETS_DIR, n)) for n in os.listdir(ASSETS_DIR))
    print(f"Written {os.path.join(OUT_DIR, 'index.html')}")
    print(f"Written {os.path.join(OUT_DIR, 'config.js')}")
    print(f"Assets: {asset_count} files ({asset_bytes / 1024 / 1024:.1f} MB)")


WIRE_SCRIPT = """
<script>
(function() {
  function cfg() {
    return window.KAKUTO_LP || {};
  }

  function scrollToHash(hash) {
    var id = (hash || "").replace(/^#/, "");
    if (!id) return;
    var target = document.getElementById(id);
    if (target) target.scrollIntoView({ behavior: "smooth" });
  }

  function submitLead(form, event) {
    if (event) event.preventDefault();
    var c = cfg();
    var emailInput = form.querySelector('input[name="email"]');
    var companyInput = form.querySelector('input[name="company"]');
    var nameInput = form.querySelector('input[name="name"]');
    var addr = emailInput ? emailInput.value.trim() : "";
    if (!addr) {
      if (emailInput) emailInput.focus();
      return false;
    }
    var email = c.contactEmail || "contact@kakuto.ai";
    var subject = encodeURIComponent("Kakuto PoC相談・資料請求");
    var body = encodeURIComponent(
      "PoC相談・資料請求\\n\\n" +
      "会社名: " + ((companyInput && companyInput.value.trim()) || "(未入力)") + "\\n" +
      "お名前: " + ((nameInput && nameInput.value.trim()) || "(未入力)") + "\\n" +
      "メール: " + addr + "\\n\\n" +
      "相談内容: RAGに蓄積されたデータからの設計書・見積もり・提案書生成について"
    );
    window.location.href = "mailto:" + email + "?subject=" + subject + "&body=" + body;
    return false;
  }

  window.kakutoSubmitLead = submitLead;

  document.addEventListener("DOMContentLoaded", function() {
    var c = cfg();

    document.querySelectorAll("a, button").forEach(function(el) {
      var text = (el.textContent || "").trim();

      if (/デモを予約|PoCについて相談/.test(text)) {
        el.addEventListener("click", function(e) {
          if (c.calendlyUrl) {
            e.preventDefault();
            window.open(c.calendlyUrl, "_blank");
            return;
          }
          var dest = c.demoCta || "#cta";
          if (dest.charAt(0) === "#") {
            e.preventDefault();
            scrollToHash(dest);
          } else {
            var anchor = el.closest("a");
            if (anchor) anchor.href = dest;
            else if (el.tagName !== "A") {
              e.preventDefault();
              window.location.href = dest;
            }
          }
        });
      }

      if (/PoCを見る|製品デモ|ライブデモ/.test(text) && c.liveDemoUrl) {
        el.addEventListener("click", function(e) {
          e.preventDefault();
          window.open(c.liveDemoUrl, "_blank");
        });
      }
    });

    document.addEventListener("submit", function(e) {
      var form = e.target && e.target.closest ? e.target.closest("form[data-kakuto-lead-form]") : null;
      if (!form) return;
      submitLead(form, e);
    });

    document.querySelectorAll('a[href^="#"]').forEach(function(a) {
      a.addEventListener("click", function(e) {
        var id = a.getAttribute("href").slice(1);
        if (!id) return;
        var target = document.getElementById(id);
        if (target) {
          e.preventDefault();
          target.scrollIntoView({ behavior: "smooth" });
        }
      });
    });
  });
})();
</script>
"""


if __name__ == "__main__":
    main()
