#!/usr/bin/env python3
"""Deterministic synthetic JP manufacturing corpus + eval-set generator (Wave 1a scale bench).

Generates N documents (規程 / 手順書 / トラブル事例 / 点検基準) in the style of
``tests/fixtures/uat/golden_corpus.json`` and ``scripts/demo/demo_docs.json``:

- unique business-identifier tokens (equipment ids ``EQ-PRESS-042``, alarm codes ``E-217``,
  part numbers ``PN-10312``, document numbers ``SOP-0042`` / ``TR-2025-042`` / ``INS-0042`` /
  ``REG-0042``) so identifier retrieval is measurable;
- a SHARED manufacturing vocabulary (families / components / symptoms / actions / filler
  sentences) reused across documents so lexical retrieval faces real distractors — many
  documents share 2 of the 3 (family, component, symptom) content anchors of any query;
- an eval set (~200 queries) with gold document_ids across five slices:
  identifier lookup / paraphrase (natural JP, no identifiers) / synonym (a key symptom term is
  replaced by a zero-bigram-overlap synonym) / multi-doc (2-3 golds sharing an equipment id) /
  unanswerable (~15%; reserved identifier ranges + out-of-domain topics).

Everything is seeded (``random.Random(seed)``); NO wall-clock or uuid nondeterminism — the same
(seed, n_docs, n_queries) always yields byte-identical output (verified by
``tests/unit/test_bench_generator.py``). Stdlib-only.

CLI:
    python3 scripts/bench/generate_corpus.py --n-docs 3000 --n-queries 200 --seed 20260703 \
        --out /tmp/bench_corpus.json
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict

MAX_DOCS = 20_000  # keeps sequential doc numbers below the reserved 9xxx unanswerable range

# --- shared vocabulary (deliberately reused across documents to create distractors) ---

EQUIPMENT_FAMILIES: tuple[tuple[str, str], ...] = (
    ("PRESS", "プレス機"),
    ("MOLD", "射出成形機"),
    ("LATHE", "CNC旋盤"),
    ("MILL", "マシニングセンタ"),
    ("CONV", "搬送コンベア"),
    ("WELD", "溶接ロボット"),
    ("INSP", "三次元測定機"),
    ("COMP", "コンプレッサ"),
    ("PAINT", "塗装ブース"),
    ("FURN", "熱処理炉"),
)

COMPONENTS: tuple[str, ...] = (
    "温度センサ",
    "油圧ポンプ",
    "アキュムレータ",
    "主軸ベアリング",
    "サーボモータ",
    "カップリング",
    "電磁弁",
    "エアフィルタ",
    "冷却ファン",
    "中継コネクタ",
    "チャック爪",
    "ボールねじ",
    "減速機",
    "リミットスイッチ",
    "シールパッキン",
    "バンドヒータ",
    "吐出ノズル",
    "駆動チェーン",
    "集塵ダクト",
    "熱電対",
    "圧力計",
    "潤滑ユニット",
    "操作パネル",
    "安全柵センサ",
)

# Symptom vocabulary. Keys of SYMPTOM_SYNONYMS are the surface forms used in DOCUMENTS; the
# synonym eval slice replaces them with the mapped query-only form. Each pair is chosen to have
# ZERO CJK-bigram overlap with its document form (asserted below), so the slice measures a true
# vocabulary miss for the lexical leg / hashing embedder — the 1c (synonym expansion) signal.
SYMPTOM_SYNONYMS: dict[str, str] = {
    "温度上昇": "オーバーヒート",
    "油圧低下": "圧力不足",
    "異音": "うなり音",
    "油漏れ": "オイルリーク",
    "過負荷": "オーバーロード",
    "非常停止": "緊急ストップ",
    "振動増大": "揺れの悪化",
    "寸法不良": "公差外れ",
    "芯ずれ": "ミスアライメント",
    "動作不良": "誤作動",
}

SYMPTOMS: tuple[str, ...] = tuple(SYMPTOM_SYNONYMS) + (
    "絶縁低下",
    "圧力変動",
    "通信異常",
    "目詰まり",
    "焼付き",
    "経年劣化",
)

ACTIONS: tuple[str, ...] = (
    "新品に交換する",
    "増締めを行う",
    "分解清掃を行う",
    "グリスを補給する",
    "再校正を実施する",
    "制御装置を再起動する",
    "配線を差し直す",
    "設定値を初期化する",
)

FACTORIES: tuple[str, ...] = ("第一工場", "第二工場", "第三工場")
LINES: tuple[str, ...] = ("Aライン", "Bライン", "Cライン", "Dライン")

FILLER_SENTENCES: tuple[str, ...] = (
    "作業前に主電源を遮断し、ロックアウト・タグアウトを実施すること。",
    "作業時は保護メガネと耐切創手袋を着用すること。",
    "結果は設備保全記録に記入し、係長の承認を受けること。",
    "異常を発見した場合は直ちにラインを停止し、設備保全課へ連絡すること。",
    "本書の改訂は品質保証部の承認を経て行う。",
    "測定器は校正有効期限内のものを使用すること。",
    "作業完了後は周囲の清掃と工具の員数確認を行うこと。",
    "判定に迷う場合は上位の検査基準書を参照すること。",
)

REGULATION_TOPICS: tuple[str, ...] = (
    "安全衛生",
    "品質記録",
    "変更管理",
    "計測機器管理",
    "保護具着用",
    "教育訓練",
    "5S活動",
    "静電気対策",
    "化学物質取扱",
    "外注品受入",
)

# Out-of-domain topics for the unanswerable slice (never generated as documents).
OUT_OF_DOMAIN_QUESTIONS: tuple[str, ...] = (
    "経費精算の締め日はいつですか。",
    "有給休暇の繰越上限日数を教えてください。",
    "社員食堂の営業時間を教えてください。",
    "通勤手当の支給基準はどこに書かれていますか。",
    "中途採用の面接プロセスを教えてください。",
    "社宅の入居条件を教えてください。",
)

# Query slice mix (fractions of n_queries).
QUERY_MIX: tuple[tuple[str, float], ...] = (
    ("identifier", 0.30),
    ("paraphrase", 0.25),
    ("synonym", 0.15),
    ("multi_doc", 0.15),
    ("unanswerable", 0.15),
)

_KINDS: tuple[tuple[str, str, float], ...] = (
    # (document_kind, 日本語種別, share of corpus)
    ("work_instruction", "手順書", 0.30),
    ("trouble_report", "トラブル事例", 0.30),
    ("inspection", "点検基準", 0.20),
    ("regulation", "規程", 0.20),
)


def _bigrams(text: str) -> set[str]:
    return {text[i : i + 2] for i in range(len(text) - 1)}


def _assert_synonym_pairs_disjoint() -> None:
    for doc_form, query_form in SYMPTOM_SYNONYMS.items():
        overlap = _bigrams(doc_form) & _bigrams(query_form)
        if overlap:
            raise AssertionError(
                f"synonym pair {doc_form!r}->{query_form!r} shares bigrams {overlap}; "
                "the synonym slice must measure a true vocabulary miss"
            )


_assert_synonym_pairs_disjoint()


def _iso_date(rng: random.Random) -> str:
    year = rng.randint(2023, 2026)
    month = rng.randint(1, 12)
    day = rng.randint(1, 28)
    return f"{year:04d}-{month:02d}-{day:02d}"


def _pick_equipment(rng: random.Random, n_docs: int) -> tuple[str, str, str]:
    """(family_code, family_jp, equipment_id). Numbers stay < 900; 9xx is reserved unanswerable."""
    fam_code, fam_jp = rng.choice(EQUIPMENT_FAMILIES)
    per_family = max(3, min(899, n_docs // (4 * len(EQUIPMENT_FAMILIES))))
    number = rng.randint(1, per_family)
    return fam_code, fam_jp, f"EQ-{fam_code}-{number:03d}"


def _work_instruction(rng: random.Random, seq: int, n_docs: int, alarm_pairs: set) -> dict:
    _, fam_jp, equipment_id = _pick_equipment(rng, n_docs)
    component = rng.choice(COMPONENTS)
    symptom = rng.choice(SYMPTOMS)
    # unique (equipment_id, alarm_code): alarm numbers 100-499; 9xx reserved for unanswerable.
    for _ in range(64):
        alarm_code = f"E-{rng.randint(100, 499)}"
        if (equipment_id, alarm_code) not in alarm_pairs:
            break
    alarm_pairs.add((equipment_id, alarm_code))
    action = rng.choice(ACTIONS)
    doc_no = f"SOP-{seq:04d}"
    factory = rng.choice(FACTORIES)
    line = rng.choice(LINES)
    fillers = rng.sample(FILLER_SENTENCES, 2)
    minutes = rng.randint(5, 40)
    content = (
        f"{fam_jp} {equipment_id} {component}対応手順書({doc_no})。"
        f"対象設備:{factory}{line} {fam_jp} {equipment_id}。"
        f"アラーム {alarm_code} は{component}の{symptom}を示す。"
        f"処置手順: 1) 運転を停止し安全確認を行う。 2) {component}の状態を目視確認する。 "
        f"3) 異常が認められた場合は{component}を{action}。 4) 復旧後 {minutes} 分間の試運転で"
        f"アラーム {alarm_code} が再発しないことを確認する。"
        f"{fillers[0]}{fillers[1]}"
    )
    return {
        "document_id": f"sop_{seq:04d}",
        "title": f"{fam_jp} {component}対応手順書 {doc_no}",
        "content": content,
        "document_kind": "work_instruction",
        "doc_no": doc_no,
        "equipment_id": equipment_id,
        "alarm_code": alarm_code,
        "part_no": "",
        "family_jp": fam_jp,
        "component": component,
        "symptom": symptom,
    }


def _trouble_report(rng: random.Random, seq: int, n_docs: int) -> dict:
    _, fam_jp, equipment_id = _pick_equipment(rng, n_docs)
    component = rng.choice(COMPONENTS)
    symptom = rng.choice(SYMPTOMS)
    action = rng.choice(ACTIONS)
    doc_no = f"TR-2025-{seq:03d}"
    part_no = f"PN-{10000 + seq}"
    factory = rng.choice(FACTORIES)
    line = rng.choice(LINES)
    downtime = rng.randint(10, 480)
    cause = rng.choice(
        (
            "締結ボルトの緩み",
            "経年による摩耗",
            "冷却水の流量不足",
            "設定パラメータの誤り",
            "端子部の接触不良",
            "異物の混入",
        )
    )
    fillers = rng.sample(FILLER_SENTENCES, 2)
    content = (
        f"トラブル事例報告書 {doc_no}。発生設備:{factory}{line} {fam_jp} {equipment_id}。"
        f"事象:{component}の{symptom}により生産が {downtime} 分間停止した。"
        f"原因調査の結果、{cause}と特定した。"
        f"恒久対策として{component}({part_no})を{action}。"
        f"水平展開として同型設備の{component}を臨時点検した。"
        f"{fillers[0]}{fillers[1]}"
    )
    return {
        "document_id": f"tr_{seq:04d}",
        "title": f"トラブル事例 {doc_no} {fam_jp} {component}{symptom}",
        "content": content,
        "document_kind": "trouble_report",
        "doc_no": doc_no,
        "equipment_id": equipment_id,
        "alarm_code": "",
        "part_no": part_no,
        "family_jp": fam_jp,
        "component": component,
        "symptom": symptom,
    }


def _inspection(rng: random.Random, seq: int, n_docs: int) -> dict:
    _, fam_jp, equipment_id = _pick_equipment(rng, n_docs)
    component = rng.choice(COMPONENTS)
    symptom = rng.choice(SYMPTOMS)
    action = rng.choice(ACTIONS)
    doc_no = f"INS-{seq:04d}"
    interval = rng.choice(("日常", "週次", "月次", "3ヶ月ごと", "6ヶ月ごと", "年次"))
    value = rng.choice(("0.02", "0.05", "0.10", "0.3", "0.5", "1.5", "2.0", "75", "80"))
    unit = rng.choice(("mm", "MPa", "℃", "mm/s", "dB(A)"))
    fillers = rng.sample(FILLER_SENTENCES, 2)
    content = (
        f"点検基準書 {doc_no}({fam_jp} {equipment_id})。"
        f"{component}は{interval}に点検し、{symptom}の兆候がないことを確認する。"
        f"測定値が基準値 {value}{unit} を超えた場合は{component}を{action}。"
        f"点検結果はチェックシートに記録し、月末に設備保全課へ提出する。"
        f"{fillers[0]}{fillers[1]}"
    )
    return {
        "document_id": f"ins_{seq:04d}",
        "title": f"{fam_jp} {component}点検基準書 {doc_no}",
        "content": content,
        "document_kind": "inspection",
        "doc_no": doc_no,
        "equipment_id": equipment_id,
        "alarm_code": "",
        "part_no": "",
        "family_jp": fam_jp,
        "component": component,
        "symptom": symptom,
    }


def _regulation(rng: random.Random, seq: int, n_docs: int) -> dict:
    topic = rng.choice(REGULATION_TOPICS)
    _, fam_jp, equipment_id = _pick_equipment(rng, n_docs)
    doc_no = f"REG-{seq:04d}"
    review_months = rng.choice((6, 12, 24))
    fillers = rng.sample(FILLER_SENTENCES, 3)
    content = (
        f"{topic}管理規程({doc_no})。"
        f"目的:当社工場における{topic}の管理基準を定め、品質と安全を確保する。"
        f"適用範囲:{fam_jp}({equipment_id} ほか)を含む全生産設備とその作業者。"
        f"本規程は {review_months} ヶ月ごとに見直しを行う。"
        f"{fillers[0]}{fillers[1]}{fillers[2]}"
    )
    return {
        "document_id": f"reg_{seq:04d}",
        "title": f"{topic}管理規程 {doc_no}",
        "content": content,
        "document_kind": "regulation",
        "doc_no": doc_no,
        "equipment_id": equipment_id,
        "alarm_code": "",
        "part_no": "",
        "family_jp": fam_jp,
        "component": "",
        "symptom": "",
    }


def _generate_documents(rng: random.Random, n_docs: int) -> list[dict]:
    counts: list[tuple[str, int]] = []
    remaining = n_docs
    for i, (kind, _jp, share) in enumerate(_KINDS):
        n = remaining if i == len(_KINDS) - 1 else int(n_docs * share)
        counts.append((kind, n))
        remaining -= n
    builders = {
        "work_instruction": _work_instruction,
        "trouble_report": _trouble_report,
        "inspection": _inspection,
        "regulation": _regulation,
    }
    alarm_pairs: set[tuple[str, str]] = set()
    docs: list[dict] = []
    for kind, n in counts:
        for seq in range(1, n + 1):
            if kind == "work_instruction":
                doc = builders[kind](rng, seq, n_docs, alarm_pairs)
            else:
                doc = builders[kind](rng, seq, n_docs)
            doc["approval_status"] = "approved"
            doc["effective_date"] = _iso_date(rng)
            docs.append(doc)
    rng.shuffle(docs)
    return docs


# --- eval-set construction ---

_PARAPHRASE_TEMPLATES: tuple[str, ...] = (
    "{family}で{component}の{symptom}が発生した場合、どう対応すればよいですか。",
    "{family}の{component}に{symptom}が見られます。処置を教えてください。",
    "{component}の{symptom}が{family}で起きたときの対処方法を知りたい。",
    "{family}を使っていて{component}の{symptom}に気づいた。確認すべきことは何か。",
)

_SYNONYM_TEMPLATES: tuple[str, ...] = (
    "{family}の{component}で{synonym}が起きたときはどうすればよいですか。",
    "{family}で{component}の{synonym}が発生しました。対応を教えてください。",
    "{component}の{synonym}が{family}で出ています。処置方法は?",
)

_IDENTIFIER_TEMPLATES: dict[str, tuple[str, ...]] = {
    "work_instruction": (
        "{equipment_id} のアラーム {alarm_code} は何を示しますか。処置も教えてください。",
        "{equipment_id} で {alarm_code} が発生しました。手順書に沿った対応を教えてください。",
    ),
    "trouble_report": (
        "トラブル報告書 {doc_no} の原因と恒久対策を教えてください。",
        "{doc_no} で交換した部品 {part_no} と対策内容を確認したい。",
    ),
    "inspection": (
        "点検基準書 {doc_no} の判定基準を教えてください。",
        "{doc_no}({equipment_id})の点検周期と基準値は?",
    ),
    "regulation": (
        "規程 {doc_no} の目的と適用範囲を教えてください。",
        "{doc_no} の見直し周期を確認したい。",
    ),
}


def _slice_counts(n_queries: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    assigned = 0
    for i, (name, frac) in enumerate(QUERY_MIX):
        n = n_queries - assigned if i == len(QUERY_MIX) - 1 else int(round(n_queries * frac))
        counts[name] = n
        assigned += n
    return counts


def _generate_queries(rng: random.Random, docs: list[dict], n_queries: int) -> list[dict]:
    counts = _slice_counts(n_queries)
    queries: list[dict] = []

    # Uniqueness index: docs whose (family, component, symptom) triple appears exactly once are
    # the only well-defined golds for identifier-free (paraphrase/synonym) queries.
    triples = Counter(
        (d["family_jp"], d["component"], d["symptom"]) for d in docs if d["component"]
    )
    unique_triple_docs = [
        d
        for d in docs
        if d["component"] and triples[(d["family_jp"], d["component"], d["symptom"])] == 1
    ]
    rng.shuffle(unique_triple_docs)
    synonym_eligible = [d for d in unique_triple_docs if d["symptom"] in SYMPTOM_SYNONYMS]

    by_equipment: dict[str, list[dict]] = defaultdict(list)
    for d in docs:
        by_equipment[d["equipment_id"]].append(d)
    multi_doc_equipment = sorted(
        (eq for eq, ds in by_equipment.items() if 2 <= len(ds) <= 3),
        key=lambda eq: eq,
    )
    rng.shuffle(multi_doc_equipment)

    qid = 0

    def _add(category: str, question: str, gold: list[str]) -> None:
        nonlocal qid
        qid += 1
        queries.append(
            {
                "query_id": f"q_{qid:04d}",
                "category": category,
                "question": question,
                "gold_document_ids": sorted(gold),
                "answerable": bool(gold),
            }
        )

    # 1) identifier lookup — the doc number / (equipment, alarm) pair is globally unique.
    identifier_pool = [d for d in docs]
    rng.shuffle(identifier_pool)
    for d in identifier_pool[: counts["identifier"]]:
        template = rng.choice(_IDENTIFIER_TEMPLATES[d["document_kind"]])
        _add("identifier", template.format(**d), [d["document_id"]])

    # 2) paraphrase — natural JP, no identifiers; gold is the unique-triple doc.
    paraphrase_docs = unique_triple_docs[: counts["paraphrase"]]
    if len(paraphrase_docs) < counts["paraphrase"]:
        raise AssertionError(
            f"not enough unique-triple docs for the paraphrase slice "
            f"({len(paraphrase_docs)} < {counts['paraphrase']}); increase n_docs"
        )
    for d in paraphrase_docs:
        template = rng.choice(_PARAPHRASE_TEMPLATES)
        _add(
            "paraphrase",
            template.format(family=d["family_jp"], component=d["component"], symptom=d["symptom"]),
            [d["document_id"]],
        )

    # 3) synonym — same as paraphrase but the symptom surface form is replaced by a
    #    zero-bigram-overlap synonym (never present in any document text).
    used = {d["document_id"] for d in paraphrase_docs}
    synonym_docs = [d for d in synonym_eligible if d["document_id"] not in used]
    synonym_docs = synonym_docs[: counts["synonym"]]
    if len(synonym_docs) < counts["synonym"]:
        raise AssertionError(
            f"not enough unique-triple synonym docs ({len(synonym_docs)} < {counts['synonym']}); "
            "increase n_docs"
        )
    for d in synonym_docs:
        template = rng.choice(_SYNONYM_TEMPLATES)
        _add(
            "synonym",
            template.format(
                family=d["family_jp"],
                component=d["component"],
                synonym=SYMPTOM_SYNONYMS[d["symptom"]],
            ),
            [d["document_id"]],
        )

    # 4) multi-doc — all documents of one equipment id (2-3 golds).
    for eq in multi_doc_equipment[: counts["multi_doc"]]:
        golds = [d["document_id"] for d in by_equipment[eq]]
        _add(
            "multi_doc",
            f"{eq} に関する手順書・点検基準・トラブル事例をまとめて教えてください。",
            golds,
        )
    if sum(1 for q in queries if q["category"] == "multi_doc") < counts["multi_doc"]:
        raise AssertionError("not enough multi-doc equipment clusters; increase n_docs")

    # 5) unanswerable — reserved identifier ranges (never generated) + out-of-domain topics.
    n_unanswerable = counts["unanswerable"]
    for i in range(n_unanswerable):
        style = i % 3
        if style == 0:
            fam_code, fam_jp = rng.choice(EQUIPMENT_FAMILIES)
            eq = f"EQ-{fam_code}-{rng.randint(900, 999)}"
            question = f"{eq} のアラーム E-{rng.randint(900, 999)} の対処手順を教えてください。"
        elif style == 1:
            doc_no = rng.choice(("SOP", "INS", "REG")) + f"-{rng.randint(9000, 9999)}"
            question = f"文書 {doc_no} の内容を教えてください。"
        else:
            question = rng.choice(OUT_OF_DOMAIN_QUESTIONS)
        _add("unanswerable", question, [])

    return queries


def generate(n_docs: int = 3000, n_queries: int = 200, seed: int = 20260703) -> dict:
    """Return the full benchmark corpus: ``{"documents": [...], "queries": [...]}``."""
    if not 100 <= n_docs <= MAX_DOCS:
        raise ValueError(f"n_docs must be within [100, {MAX_DOCS}]")
    rng = random.Random(seed)
    docs = _generate_documents(rng, n_docs)
    queries = _generate_queries(rng, docs, n_queries)
    return {
        "_doc": (
            "Wave 1a synthetic JP manufacturing benchmark corpus. Deterministic (seeded); "
            "generated by scripts/bench/generate_corpus.py. Do not hand-edit."
        ),
        "seed": seed,
        "n_docs": n_docs,
        "n_queries": n_queries,
        "documents": docs,
        "queries": queries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n-docs", type=int, default=3000)
    parser.add_argument("--n-queries", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260703)
    parser.add_argument("--out", type=str, required=True, help="output JSON path")
    args = parser.parse_args()
    corpus = generate(n_docs=args.n_docs, n_queries=args.n_queries, seed=args.seed)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(corpus, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print(
        f"wrote {args.out}: {len(corpus['documents'])} documents, "
        f"{len(corpus['queries'])} queries (seed={args.seed})"
    )


if __name__ == "__main__":
    main()
