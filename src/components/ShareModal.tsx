import { useState } from "react";
import { Share2, Copy, Check, X, ExternalLink, Film, Download, Sparkles, Link2 } from "lucide-react";
import type { CachedFile } from "../lib/db";
import { formatSize } from "../lib/drive";

interface Props {
  file: CachedFile;
  onClose: () => void;
}

export default function ShareModal({ file, onClose }: Props) {
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  const cleanFolderId = String(file.folderId || "").replace(/^-100/, "");
  const isVideo =
    file.mimeType.startsWith("video/") ||
    Boolean(file.name.toLowerCase().match(/\.(mp4|mkv|webm|mov|avi)$/));

  const watchUrl = `https://stream.capt-th.work/watch/${file.folderId}/${file.messageId}`;
  const dlUrl = `https://stream.capt-th.work/dl/${file.folderId}/${file.messageId}`;
  const tgUrl = `https://t.me/c/${cleanFolderId}/${file.messageId}`;
  const colabUrl = `https://colab.research.google.com/github/thawatchaijaihan/tg-drive/blob/main/tg_video_faststart_optimizer.ipynb`;

  const copy = async (key: string, url: string) => {
    try {
      await navigator.clipboard.writeText(url);
      setCopiedKey(key);
      setTimeout(() => setCopiedKey(null), 2500);
    } catch {}
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4 select-none">
      <div
        className="bg-white dark:bg-[#282a2d] border border-gray-200 dark:border-gray-700 rounded-3xl w-full max-w-lg shadow-2xl overflow-hidden animate-in zoom-in-95 duration-150"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 dark:border-gray-800">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-blue-50 dark:bg-blue-950/40 text-[#1a73e8] flex items-center justify-center flex-shrink-0">
              <Share2 size={18} />
            </div>
            <div className="min-w-0">
              <h3 className="font-medium text-base text-gray-800 dark:text-gray-100">
                Share "{file.name}"
              </h3>
              <p className="text-xs text-gray-400 truncate">
                {formatSize(file.size)} • Telegram Cloud MTProto
              </p>
            </div>
          </div>
          <button
            type="button"
            className="p-1 rounded-full text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </div>

        {/* Links */}
        <div className="p-6 space-y-4">
          {/* Public Stream Link (if video) */}
          {isVideo && (
            <div className="p-3.5 rounded-2xl bg-[#f0f4f9] dark:bg-[#1e1f20] border border-gray-200/70 dark:border-gray-700/60">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs font-semibold text-[#1a73e8] flex items-center gap-1.5">
                  <Film size={14} /> Video Stream Link (HTML5 + HLS)
                </span>
                <span className="text-[10px] text-gray-400">No Telegram account needed</span>
              </div>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
                Instantly stream online with seeking, P2P swarm, and subtitle support.
              </p>
              <div className="flex gap-2">
                <input
                  type="text"
                  readOnly
                  value={watchUrl}
                  className="w-full px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-[#282a2d] text-xs font-mono text-gray-700 dark:text-gray-200"
                />
                <button
                  type="button"
                  className={`px-3.5 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors ${
                    copiedKey === "watch"
                      ? "bg-emerald-600 text-white"
                      : "bg-[#1a73e8] text-white hover:bg-[#1557b0]"
                  }`}
                  onClick={() => copy("watch", watchUrl)}
                >
                  {copiedKey === "watch" ? <Check size={14} /> : <Copy size={14} />}
                  <span>{copiedKey === "watch" ? "Copied" : "Copy"}</span>
                </button>
              </div>
            </div>
          )}

          {/* Google Colab Faststart Optimizer Link (if video) */}
          {isVideo && (
            <div className="p-3.5 rounded-2xl bg-amber-50/70 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-900/40">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-bold text-amber-600 dark:text-amber-400 flex items-center gap-1.5">
                  <Sparkles size={14} /> FastStart Optimizer (Google Colab)
                </span>
                <span className="text-[10px] bg-amber-200 dark:bg-amber-900/60 text-amber-800 dark:text-amber-200 px-2 py-0.5 rounded-full font-medium">
                  Free T4 GPU
                </span>
              </div>
              <p className="text-xs text-gray-600 dark:text-gray-300 mb-2.5">
                Convert video for instant seek on Smart TV and Web browsers without download wait time.
              </p>
              <a
                href={colabUrl}
                target="_blank"
                rel="noreferrer"
                className="w-full py-2 px-3 rounded-xl bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 text-white text-xs font-medium flex items-center justify-center gap-2 shadow-sm transition-all"
              >
                <ExternalLink size={14} />
                Open Google Colab FastStart Notebook
              </a>
            </div>
          )}

          {/* Direct Download Link */}
          <div className="p-3.5 rounded-2xl bg-[#f0f4f9] dark:bg-[#1e1f20] border border-gray-200/70 dark:border-gray-700/60">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-xs font-semibold text-gray-700 dark:text-gray-200 flex items-center gap-1.5">
                <Download size={14} className="text-blue-500" /> Direct Download Link
              </span>
              <span className="text-[10px] text-gray-400">Direct HTTP 206</span>
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
              Direct download link through high-speed Cloudflare proxy.
            </p>
            <div className="flex gap-2">
              <input
                type="text"
                readOnly
                value={dlUrl}
                className="w-full px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-[#282a2d] text-xs font-mono text-gray-700 dark:text-gray-200"
              />
              <button
                type="button"
                className={`px-3.5 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors ${
                  copiedKey === "dl"
                    ? "bg-emerald-600 text-white"
                    : "bg-gray-800 dark:bg-gray-700 text-white hover:bg-gray-900"
                }`}
                onClick={() => copy("dl", dlUrl)}
              >
                {copiedKey === "dl" ? <Check size={14} /> : <Copy size={14} />}
                <span>{copiedKey === "dl" ? "Copied" : "Copy"}</span>
              </button>
            </div>
          </div>

          {/* Telegram In-App Link */}
          <div className="p-3.5 rounded-2xl bg-[#f0f4f9] dark:bg-[#1e1f20] border border-gray-200/70 dark:border-gray-700/60">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-xs font-semibold text-gray-700 dark:text-gray-200 flex items-center gap-1.5">
                <Link2 size={14} className="text-sky-500" /> Telegram App Message Link
              </span>
              <span className="text-[10px] text-gray-400">t.me</span>
            </div>
            <div className="flex gap-2">
              <input
                type="text"
                readOnly
                value={tgUrl}
                className="w-full px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-[#282a2d] text-xs font-mono text-gray-700 dark:text-gray-200"
              />
              <button
                type="button"
                className={`px-3.5 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors ${
                  copiedKey === "tg"
                    ? "bg-emerald-600 text-white"
                    : "bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-200 hover:bg-gray-300"
                }`}
                onClick={() => copy("tg", tgUrl)}
              >
                {copiedKey === "tg" ? <Check size={14} /> : <Copy size={14} />}
                <span>{copiedKey === "tg" ? "Copied" : "Copy"}</span>
              </button>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-3 bg-gray-50 dark:bg-[#1e1f20] border-t border-gray-100 dark:border-gray-800 flex justify-end">
          <button
            type="button"
            className="px-4 py-1.5 rounded-full text-xs font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
            onClick={onClose}
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
