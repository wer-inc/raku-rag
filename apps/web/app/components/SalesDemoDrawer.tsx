"use client";

const SALES_FILES = [
  {
    title: "承認済み作業標準",
    detail: "安全回答の根拠として使うMarkdownサンプル",
    href: "/sales-samples/approved-work-instruction.md",
    type: "MD",
  },
  {
    title: "過去トラブル事例",
    detail: "類似事例検索で使うCSVサンプル",
    href: "/sales-samples/trouble-cases.csv",
    type: "CSV",
  },
  {
    title: "文書メタデータ",
    detail: "承認状態・設備ID・ACLタグの取込確認用",
    href: "/sales-samples/document-metadata.csv",
    type: "CSV",
  },
  {
    title: "ACLマッピング",
    detail: "ロール別に見える範囲を説明するCSV",
    href: "/sales-samples/acl-mapping.csv",
    type: "CSV",
  },
  {
    title: "提案説明メモ",
    detail: "商談中の説明順をまとめたトークトラック",
    href: "/sales-samples/demo-talk-track.md",
    type: "MD",
  },
] as const;

export default function SalesDemoDrawer({
  displayName,
  onClose,
  onToggle,
  open,
}: {
  displayName: string;
  onClose: () => void;
  onToggle: () => void;
  open: boolean;
}) {
  return (
    <>
      <button
        type="button"
        className="sales-drawer-tab"
        aria-label="提案資料を開く"
        aria-expanded={open}
        onClick={onToggle}
      >
        資料
      </button>
      <button
        type="button"
        className={`sales-drawer-scrim${open ? " open" : ""}`}
        aria-label="提案資料を閉じる"
        tabIndex={open ? 0 : -1}
        onClick={onClose}
      />
      <aside className={`sales-drawer${open ? " open" : ""}`} aria-label="提案資料">
        <header className="sales-drawer-head">
          <div>
            <p className="eyebrow">Resources</p>
            <h2>提案資料</h2>
            <p>{displayName} としてログイン中です。</p>
          </div>
          <button type="button" aria-label="提案資料を閉じる" onClick={onClose}>
            ×
          </button>
        </header>
        <div className="sales-drawer-guide">
          <strong>資料セット</strong>
          <span>取込プレビュー、権限、根拠付き回答の確認に使えるファイルです。</span>
        </div>
        <div className="sales-file-list">
          {SALES_FILES.map((file) => (
            <a key={file.href} className="sales-file-item" href={file.href} download>
              <span className="sales-file-type">{file.type}</span>
              <span className="sales-file-copy">
                <strong>{file.title}</strong>
                <span>{file.detail}</span>
              </span>
              <span className="sales-file-action">ダウンロード</span>
            </a>
          ))}
        </div>
      </aside>
    </>
  );
}
