import { useState } from "react";
import { Share2, Copy, Check, X, ExternalLink, Film, Download } from "lucide-react";
import type { CachedFile } from "../lib/db";
import { formatSize } from "../lib/drive";

interface Props {
  file: CachedFile;
  onClose: () => void;
}

export default function ShareModal({ file, onClose }: Props) {
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  const cleanFolderId = String(file.folderId || "").replace(/^-100/, "");
  const isVideo = file.mimeType.startsWith("video/") || file.name.toLowerCase().match(/\.(mp4|mkv|webm|mov|avi)$/);

  const watchUrl = `https://stream.capt-th.work/watch/${file.folderId}/${file.messageId}`;
  const dlUrl = `https://stream.capt-th.work/dl/${file.folderId}/${file.messageId}`;
  const tgUrl = `https://t.me/c/${cleanFolderId}/${file.messageId}`;

  const copy = async (key: string, url: string) => {
    try {
      await navigator.clipboard.writeText(url);
      setCopiedKey(key);
      setTimeout(() => setCopiedKey(null), 2500);
    } catch {
      // fallback
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-base-100 border border-base-300 rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-base-300">
          <div className="flex items-center gap-2">
            <div className="p-2 rounded-lg bg-primary/10 text-primary">
              <Share2 size={18} />
            </div>
            <div>
              <h3 className="font-bold text-base text-base-content">แชร์ไฟล์ (Share Link)</h3>
              <p className="text-xs text-base-content/50 truncate max-w-xs">{file.name} ({formatSize(file.size)})</p>
            </div>
          </div>
          <button className="btn btn-ghost btn-xs btn-circle" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        {/* Links */}
        <div className="p-6 space-y-4">
          
          {/* Public Stream Link (if video) */}
          {isVideo && (
            <div className="p-3.5 rounded-xl bg-base-200/70 border border-base-300">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs font-semibold text-primary flex items-center gap-1.5">
                  <Film size={13} /> ลิงก์ดูวิดีโอออนไลน์ (Public Web Stream)
                </span>
                <span className="text-[10px] text-base-content/40">ไม่ต้องมี Telegram</span>
              </div>
              <p className="text-xs text-base-content/60 mb-2">เพื่อนสามารถแตะเปิดดูได้ทันทีผ่าน Chrome/Safari ลื่นไหล ไม่ต้องรอโหลด</p>
              <div className="flex gap-2">
                <input
                  type="text"
                  readOnly
                  value={watchUrl}
                  className="input input-sm input-bordered font-mono text-xs flex-1 bg-base-100"
                />
                <button
                  className={`btn btn-sm ${copiedKey === "watch" ? "btn-success" : "btn-primary"}`}
                  onClick={() => copy("watch", watchUrl)}
                >
                  {copiedKey === "watch" ? <Check size={14} /> : <Copy size={14} />}
                  {copiedKey === "watch" ? "คัดลอกแล้ว" : "คัดลอก"}
                </button>
              </div>
            </div>
          )}

          {/* Direct Download Link */}
          <div className="p-3.5 rounded-xl bg-base-200/70 border border-base-300">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-xs font-semibold text-secondary flex items-center gap-1.5">
                <Download size={13} /> ลิงก์ดาวน์โหลดตรง (Direct Download Link)
              </span>
              <span className="text-[10px] text-base-content/40">โหลดผ่านเว็บ</span>
            </div>
            <p className="text-xs text-base-content/60 mb-2">สำหรับดาวน์โหลดไฟล์เต็มลงคอมหรือมือถือผ่านเบราว์เซอร์</p>
            <div className="flex gap-2">
              <input
                type="text"
                readOnly
                value={dlUrl}
                className="input input-sm input-bordered font-mono text-xs flex-1 bg-base-100"
              />
              <button
                className={`btn btn-sm ${copiedKey === "dl" ? "btn-success" : "btn-secondary"}`}
                onClick={() => copy("dl", dlUrl)}
              >
                {copiedKey === "dl" ? <Check size={14} /> : <Copy size={14} />}
                {copiedKey === "dl" ? "คัดลอกแล้ว" : "คัดลอก"}
              </button>
            </div>
          </div>

          {/* Telegram Channel Link */}
          <div className="p-3.5 rounded-xl bg-base-200/70 border border-base-300">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-xs font-semibold text-accent flex items-center gap-1.5">
                <ExternalLink size={13} /> ลิงก์ห้องใน Telegram (In-App Link)
              </span>
              <span className="text-[10px] text-base-content/40">สำหรับคนมี Telegram</span>
            </div>
            <div className="flex gap-2">
              <input
                type="text"
                readOnly
                value={tgUrl}
                className="input input-sm input-bordered font-mono text-xs flex-1 bg-base-100"
              />
              <button
                className={`btn btn-sm btn-ghost border border-base-300 ${copiedKey === "tg" ? "btn-success text-white" : ""}`}
                onClick={() => copy("tg", tgUrl)}
              >
                {copiedKey === "tg" ? <Check size={14} /> : <Copy size={14} />}
                {copiedKey === "tg" ? "คัดลอกแล้ว" : "คัดลอก"}
              </button>
            </div>
          </div>

        </div>

        {/* Footer */}
        <div className="px-6 py-3 bg-base-200/50 border-t border-base-300 flex justify-end">
          <button className="btn btn-sm btn-ghost" onClick={onClose}>
            ปิดหน้าต่าง
          </button>
        </div>

      </div>
    </div>
  );
}
