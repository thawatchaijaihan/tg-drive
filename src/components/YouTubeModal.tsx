import { useState, useEffect, useRef } from "react";
import {
  X, Play, Loader2, AlertCircle,
  Download, Film, Music, ExternalLink, Cookie, ChevronDown, ChevronUp,
  ClipboardPaste
} from "lucide-react";

interface Props {
  folderId?: string;
  folderTitle?: string;
  onDone: () => void;
  onClose: () => void;
}

type QualityOption = "1080p" | "720p" | "480p" | "mp3";

interface TaskStatus {
  task_id: string;
  url: string;
  folder_id: number;
  quality: string;
  status: "queued" | "fetching_info" | "downloading" | "merging" | "uploading" | "completed" | "failed";
  progress: number;
  speed?: string;
  eta?: string;
  title?: string;
  msg_id?: number;
  error?: string;
}

export default function YouTubeModal({ folderId = "3525937661", folderTitle = "YouTube", onDone, onClose }: Props) {
  const [url, setUrl] = useState("");
  const [quality, setQuality] = useState<QualityOption>("1080p");
  const [loading, setLoading] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [taskStatus, setTaskStatus] = useState<TaskStatus | null>(null);
  const [errorMsg, setErrorMsg] = useState("");
  const [showCookieSettings, setShowCookieSettings] = useState(false);
  const [cookieText, setCookieText] = useState("");
  const [cookieSaving, setCookieSaving] = useState(false);
  const [cookieSaveResult, setCookieSaveResult] = useState<string | null>(null);

  const pollIntervalRef = useRef<number | null>(null);

  // Auto-paste clipboard if URL looks like youtube
  const handlePasteClipboard = async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text && (text.includes("youtube.com") || text.includes("youtu.be"))) {
        setUrl(text.trim());
      }
    } catch {
      // Ignore clipboard permission errors
    }
  };

  const handleStartImport = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const cleanUrl = url.trim();
    if (!cleanUrl) return;

    setLoading(true);
    setErrorMsg("");
    setTaskStatus(null);

    // Target folder ID: use current folder if inside one, or default 3525937661
    const targetFolderId = folderId || "3525937661";

    try {
      const res = await fetch("https://stream.capt-th.work/api/youtube/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: cleanUrl,
          folder_id: targetFolderId,
          quality: quality,
        }),
      });

      const data = await res.json();
      if (!res.ok || data.error) {
        throw new Error(data.error || "เกิดข้อผิดพลาดในการเริ่มดาวน์โหลด");
      }

      setTaskId(data.task_id);
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : "ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์แปลงวิดีโอได้");
      setLoading(false);
    }
  };

  // Poll task status
  useEffect(() => {
    if (!taskId) return;

    const checkStatus = async () => {
      try {
        const res = await fetch(`https://stream.capt-th.work/api/youtube/status/${taskId}`);
        if (!res.ok) return;
        const data: TaskStatus = await res.json();
        setTaskStatus(data);

        if (data.status === "completed") {
          setLoading(false);
          if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
          onDone(); // refresh file list
        } else if (data.status === "failed") {
          setLoading(false);
          if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
          setErrorMsg(data.error || "การดาวน์โหลดล้มเหลว");
        }
      } catch {
        // network retry
      }
    };

    checkStatus();
    pollIntervalRef.current = window.setInterval(checkStatus, 2000);

    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, [taskId, onDone]);

  const handleSaveCookies = async () => {
    if (!cookieText.trim()) return;
    setCookieSaving(true);
    setCookieSaveResult(null);
    try {
      const res = await fetch("https://stream.capt-th.work/api/youtube/cookies", {
        method: "POST",
        headers: { "Content-Type": "text/plain" },
        body: cookieText.trim(),
      });
      const data = await res.json();
      if (res.ok && data.status === "ok") {
        setCookieSaveResult("✅ บันทึก cookies.txt สำเร็จ!");
        setCookieText("");
      } else {
        setCookieSaveResult(`❌ ${data.error || "เกิดข้อผิดพลาด"}`);
      }
    } catch (e: unknown) {
      setCookieSaveResult(`❌ ไม่สามารถส่งข้อมูลได้: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setCookieSaving(false);
    }
  };

  const isCompleted = taskStatus?.status === "completed";
  const isFailed = taskStatus?.status === "failed" || Boolean(errorMsg);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-xs select-none">
      <div
        className="w-full max-w-lg bg-white dark:bg-[#202124] border border-gray-200 dark:border-gray-700 rounded-3xl p-6 shadow-2xl animate-in zoom-in-95 duration-150 text-gray-800 dark:text-gray-100 flex flex-col gap-5 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* ── Header ── */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-2xl bg-red-600 flex items-center justify-center text-white shadow-md shadow-red-500/20">
              <Play size={20} className="fill-white translate-x-0.5" />
            </div>
            <div>
              <h3 className="text-lg font-medium tracking-tight">นำเข้าจาก YouTube</h3>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                แปลงเป็น MP4 FastStart เข้าสู่โฟลเดอร์ <span className="font-semibold text-blue-600 dark:text-blue-400">[{folderTitle}]</span>
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-full text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* ── Status View when Task Active / Completed ── */}
        {taskStatus && (
          <div className="p-4 rounded-2xl bg-gray-50 dark:bg-[#282a2d] border border-gray-200/80 dark:border-gray-700/80 flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                สถานะการประมวลผล
              </span>
              <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-blue-100 dark:bg-blue-900/40 text-blue-600 dark:text-blue-400">
                {taskStatus.status === "downloading" && "📥 กำลังดาวน์โหลด"}
                {taskStatus.status === "merging" && "⚙️ กำลังรวมภาพ/เสียง"}
                {taskStatus.status === "uploading" && "📤 กำลังอัปโหลด TG-Drive"}
                {taskStatus.status === "completed" && "✅ สำเร็จ"}
                {taskStatus.status === "failed" && "❌ ล้มเหลว"}
                {(taskStatus.status === "queued" || taskStatus.status === "fetching_info") && "⏳ กำลังดึงข้อมูล"}
              </span>
            </div>

            {/* Title if available */}
            {taskStatus.title && (
              <div className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
                🎬 {taskStatus.title}
              </div>
            )}

            {/* Progress bar */}
            {!isCompleted && !isFailed && (
              <div className="w-full flex flex-col gap-1.5">
                <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2.5 overflow-hidden">
                  <div
                    className="bg-blue-600 h-2.5 rounded-full transition-all duration-300"
                    style={{ width: `${Math.max(taskStatus.progress || 0, 5)}%` }}
                  />
                </div>
                <div className="flex justify-between text-xs text-gray-500 dark:text-gray-400">
                  <span>
                    {taskStatus.status === "downloading" && `${taskStatus.progress}%`}
                    {taskStatus.status === "uploading" && `${taskStatus.progress}%`}
                    {taskStatus.status === "merging" && "99% (FastStart)"}
                  </span>
                  <span>
                    {taskStatus.speed && `${taskStatus.speed}`}
                    {taskStatus.eta && ` • เหลือ ${taskStatus.eta}`}
                  </span>
                </div>
              </div>
            )}

            {/* Success Action Buttons */}
            {isCompleted && (
              <div className="flex items-center gap-2 pt-2 border-t border-gray-200 dark:border-gray-700">
                <a
                  href={`https://stream.capt-th.work/watch/${taskStatus.folder_id}/${taskStatus.msg_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-medium text-xs transition-colors shadow-sm"
                >
                  <Play size={14} className="fill-white" />
                  <span>ดูสตรีมมิ่งสด</span>
                  <ExternalLink size={12} />
                </a>
                <button
                  type="button"
                  onClick={onClose}
                  className="py-2 px-4 rounded-xl bg-gray-200 dark:bg-gray-700 hover:bg-gray-300 dark:hover:bg-gray-600 text-xs font-medium transition-colors"
                >
                  เสร็จสิ้น
                </button>
              </div>
            )}
          </div>
        )}

        {/* ── Error Alert ── */}
        {errorMsg && (
          <div className="p-3.5 rounded-2xl bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900 text-red-600 dark:text-red-400 text-xs flex items-start gap-2.5">
            <AlertCircle size={16} className="flex-shrink-0 mt-0.5" />
            <div className="flex-1 leading-relaxed">
              <p className="font-semibold mb-0.5">เกิดข้อผิดพลาด</p>
              <p className="break-all">{errorMsg}</p>
              {errorMsg.toLowerCase().includes("bot") && (
                <button
                  type="button"
                  onClick={() => setShowCookieSettings(true)}
                  className="mt-2 text-xs font-semibold text-blue-600 dark:text-blue-400 underline"
                >
                  คลิกที่นี่เพื่ออัปเดต cookies.txt (Bypass BotGuard)
                </button>
              )}
            </div>
          </div>
        )}

        {/* ── Form: URL & Quality ── */}
        {!isCompleted && (
          <form onSubmit={handleStartImport} className="flex flex-col gap-4">
            {/* Input URL */}
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-gray-600 dark:text-gray-300">
                ลิงก์วิดีโอ YouTube
              </label>
              <div className="relative flex items-center">
                <input
                  type="url"
                  required
                  placeholder="https://www.youtube.com/watch?v=... หรือ https://youtu.be/..."
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  disabled={loading}
                  className="w-full px-4 py-3 pr-20 bg-gray-50 dark:bg-[#131314] border border-gray-200 dark:border-gray-700 rounded-2xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500 transition-all"
                />
                <button
                  type="button"
                  onClick={handlePasteClipboard}
                  title="วางจากคลิปบอร์ด"
                  className="absolute right-2 px-2.5 py-1.5 rounded-xl bg-white dark:bg-[#282a2d] hover:bg-gray-100 dark:hover:bg-[#333538] text-gray-500 dark:text-gray-300 text-xs font-medium border border-gray-200 dark:border-gray-700 flex items-center gap-1.5 transition-colors shadow-2xs"
                >
                  <ClipboardPaste size={14} />
                  <span>วาง</span>
                </button>
              </div>
            </div>

            {/* Quality Selector */}
            <div className="flex flex-col gap-2">
              <label className="text-xs font-medium text-gray-600 dark:text-gray-300">
                คุณภาพวิดีโอ
              </label>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {[
                  { id: "1080p", label: "1080p FHD", sub: "คมชัดสูงสุด", icon: Film },
                  { id: "720p", label: "720p HD", sub: "โหลดเร็ว", icon: Film },
                  { id: "480p", label: "480p SD", sub: "ประหยัดเน็ต", icon: Film },
                  { id: "mp3", label: "MP3 เสียง", sub: "เฉพาะเสียง", icon: Music },
                ].map((opt) => {
                  const Icon = opt.icon;
                  const isSelected = quality === opt.id;
                  return (
                    <button
                      key={opt.id}
                      type="button"
                      onClick={() => setQuality(opt.id as QualityOption)}
                      disabled={loading}
                      className={`flex flex-col items-center justify-center p-2.5 rounded-2xl border text-center transition-all ${
                        isSelected
                          ? "border-blue-600 bg-blue-50/50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 font-medium shadow-xs"
                          : "border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-[#282a2d] text-gray-700 dark:text-gray-300"
                      }`}
                    >
                      <Icon size={16} className="mb-1" />
                      <span className="text-xs font-semibold">{opt.label}</span>
                      <span className="text-[10px] text-gray-400">{opt.sub}</span>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Action Buttons */}
            <div className="flex items-center justify-end gap-2.5 pt-2">
              <button
                type="button"
                onClick={onClose}
                disabled={loading}
                className="px-4 py-2.5 rounded-full text-xs font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
              >
                ยกเลิก
              </button>
              <button
                type="submit"
                disabled={loading || !url.trim()}
                className="flex items-center gap-2 px-6 py-2.5 rounded-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-xs font-medium transition-all shadow-md shadow-blue-500/20"
              >
                {loading ? (
                  <>
                    <Loader2 size={15} className="animate-spin" />
                    <span>กำลังประมวลผล...</span>
                  </>
                ) : (
                  <>
                    <Download size={15} />
                    <span>เริ่มแปลงและนำเข้า</span>
                  </>
                )}
              </button>
            </div>
          </form>
        )}

        {/* ── Collapsible Cookies Settings Section ── */}
        <div className="border-t border-gray-100 dark:border-gray-800 pt-3">
          <button
            type="button"
            onClick={() => setShowCookieSettings((prev) => !prev)}
            className="w-full flex items-center justify-between text-xs text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200 transition-colors py-1"
          >
            <div className="flex items-center gap-1.5 font-medium">
              <Cookie size={14} className="text-amber-500" />
              <span>การตั้งค่าคุกกี้ YouTube (Cookie Bypass)</span>
            </div>
            {showCookieSettings ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>

          {showCookieSettings && (
            <div className="mt-3 p-3.5 rounded-2xl bg-gray-50 dark:bg-[#1a1b1d] border border-gray-200 dark:border-gray-700 text-xs flex flex-col gap-2.5">
              <p className="text-gray-500 dark:text-gray-400 leading-relaxed">
                คุกกี้ช่วยให้เซิร์ฟเวอร์สามารถข้ามการตรวจจับบอทของ YouTube ได้ (ปัจจุบันเซิร์ฟเวอร์ติดตั้ง cookies.txt ไว้แล้ว)
              </p>
              <textarea
                rows={3}
                placeholder="วางข้อความจากไฟล์ cookies.txt ที่นี่หากต้องการอัปเดต..."
                value={cookieText}
                onChange={(e) => setCookieText(e.target.value)}
                className="w-full p-2.5 bg-white dark:bg-[#131314] border border-gray-200 dark:border-gray-700 rounded-xl font-mono text-[11px] focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <div className="flex items-center justify-between">
                {cookieSaveResult && <span className="text-xs">{cookieSaveResult}</span>}
                <button
                  type="button"
                  onClick={handleSaveCookies}
                  disabled={cookieSaving || !cookieText.trim()}
                  className="ml-auto px-3.5 py-1.5 rounded-xl bg-gray-800 dark:bg-gray-700 hover:bg-gray-900 text-white font-medium text-xs disabled:opacity-40 transition-colors"
                >
                  {cookieSaving ? "กำลังบันทึก..." : "บันทึกคุกกี้"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
