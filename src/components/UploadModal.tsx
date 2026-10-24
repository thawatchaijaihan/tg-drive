import { useState, useRef } from "react";
import type { DragEvent } from "react";
import { Upload, X, CheckCircle2, AlertCircle, Plus } from "lucide-react";
import { uploadFile, formatSize } from "../lib/drive";
import { FileIconComponent } from "./GoogleDriveIcons";

interface Props {
  folderId: string;
  onDone: () => void;
  onClose: () => void;
}

interface FileStatus {
  file: File;
  progress: number;
  status: "pending" | "uploading" | "done" | "error";
  error?: string;
  speedText?: string;
  etaText?: string;
  partText?: string;
}

export default function UploadModal({ folderId, onDone, onClose }: Props) {
  const [files, setFiles] = useState<FileStatus[]>([]);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = (newFiles: File[]) => {
    setFiles((prev) => [
      ...prev,
      ...newFiles.map((f) => ({ file: f, progress: 0, status: "pending" as const })),
    ]);
  };

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    addFiles(Array.from(e.dataTransfer.files));
  };

  const handleUpload = async () => {
    setUploading(true);
    for (let i = 0; i < files.length; i++) {
      if (files[i].status === "done") continue;
      setFiles((prev) =>
        prev.map((f, idx) => (idx === i ? { ...f, status: "uploading" as const } : f))
      );
      try {
        await uploadFile(folderId, files[i].file, (pct, detail) => {
          setFiles((prev) =>
            prev.map((f, idx) =>
              idx === i
                ? {
                    ...f,
                    progress: Math.round(pct * 100),
                    speedText: detail?.speedText,
                    etaText: detail?.etaText,
                    partText: detail?.partText,
                  }
                : f
            )
          );
        });
        setFiles((prev) =>
          prev.map((f, idx) => (idx === i ? { ...f, status: "done" as const, progress: 100 } : f))
        );
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : "Upload failed";
        setFiles((prev) =>
          prev.map((f, idx) => (idx === i ? { ...f, status: "error" as const, error: msg } : f))
        );
      }
    }
    setUploading(false);
    onDone();
  };

  const allDone = files.length > 0 && files.every((f) => f.status === "done");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-xs select-none">
      <div
        className="w-full max-w-lg bg-white dark:bg-[#282a2d] border border-gray-200 dark:border-gray-700 rounded-3xl p-6 shadow-2xl animate-in zoom-in-95 duration-150"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-xl font-normal text-gray-800 dark:text-gray-100 flex items-center gap-2.5">
            <Upload size={22} className="text-[#1a73e8]" />
            <span>File upload</span>
          </h3>
          <button
            type="button"
            onClick={onClose}
            disabled={uploading}
            className="p-1 rounded-full text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {files.length === 0 && (
          <div
            className={`border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition-all ${
              dragging
                ? "border-[#1a73e8] bg-blue-50/50 dark:bg-blue-950/20"
                : "border-gray-300 dark:border-gray-700 hover:border-[#1a73e8] hover:bg-gray-50/50 dark:hover:bg-gray-800/30"
            }`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
            onClick={() => inputRef.current?.click()}
          >
            <div className="w-14 h-14 rounded-full bg-blue-50 dark:bg-blue-950/40 text-[#1a73e8] flex items-center justify-center mx-auto mb-3">
              <Upload size={26} />
            </div>
            <p className="text-sm font-medium text-gray-700 dark:text-gray-200">
              Drag &amp; drop files here, or click to browse
            </p>
            <p className="text-xs text-gray-400 mt-1">
              Direct MTProto Upload • Auto-splits chunks &gt; 2 GB • Unlimited Free Cloud
            </p>
          </div>
        )}

        {files.length > 0 && (
          <div className="space-y-2.5 max-h-72 overflow-y-auto pr-1">
            {files.map((f, i) => (
              <div
                key={i}
                className="bg-[#f0f4f9] dark:bg-[#1e1f20] rounded-xl p-3 border border-gray-200/60 dark:border-gray-700/60"
              >
                <div className="flex items-center justify-between mb-1.5 gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <FileIconComponent name={f.file.name} size={18} />
                    <span className="text-xs font-medium text-gray-800 dark:text-gray-200 truncate">
                      {f.file.name}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    {f.partText && (
                      <span className="text-[10px] bg-blue-100 dark:bg-blue-950 text-blue-700 dark:text-blue-300 px-2 py-0.5 rounded-full font-mono">
                        {f.partText}
                      </span>
                    )}
                    <span className="text-xs text-gray-400">{formatSize(f.file.size)}</span>
                    {f.status === "done" && <CheckCircle2 size={16} className="text-emerald-500" />}
                    {f.status === "error" && <AlertCircle size={16} className="text-red-500" />}
                  </div>
                </div>

                {(f.status === "uploading" || f.status === "done") && (
                  <div className="mt-2">
                    <div className="w-full bg-gray-200 dark:bg-gray-700 h-1.5 rounded-full overflow-hidden">
                      <div
                        className="bg-[#1a73e8] h-full rounded-full transition-all duration-150"
                        style={{ width: `${f.progress}%` }}
                      />
                    </div>
                    {f.status === "uploading" && (
                      <div className="flex items-center justify-between text-[11px] text-gray-500 mt-1 font-mono">
                        <span>{f.progress}%</span>
                        <div className="flex items-center gap-3">
                          {f.speedText && <span className="text-blue-600 dark:text-blue-400">{f.speedText}</span>}
                          {f.etaText && <span>ETA: {f.etaText}</span>}
                        </div>
                      </div>
                    )}
                  </div>
                )}
                {f.status === "error" && <p className="text-xs text-red-500 mt-1">{f.error}</p>}
              </div>
            ))}
          </div>
        )}

        {files.length > 0 && !uploading && !allDone && (
          <button
            type="button"
            className="inline-flex items-center gap-1.5 text-xs text-blue-600 dark:text-blue-400 font-medium mt-3 hover:underline"
            onClick={() => inputRef.current?.click()}
          >
            <Plus size={14} /> Add more files
          </button>
        )}

        <input
          ref={inputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => {
            if (e.target.files) addFiles(Array.from(e.target.files));
          }}
        />

        <div className="flex items-center justify-end gap-2 mt-6 pt-2 border-t border-gray-100 dark:border-gray-800">
          <button
            type="button"
            className="px-4 py-2 rounded-full text-sm font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
            onClick={onClose}
            disabled={uploading}
          >
            {allDone ? "Close" : "Cancel"}
          </button>
          {!allDone && files.length > 0 && (
            <button
              type="button"
              className="px-5 py-2 rounded-full text-sm font-medium bg-[#1a73e8] hover:bg-[#1557b0] text-white shadow-xs transition-colors flex items-center gap-2 disabled:opacity-60"
              onClick={handleUpload}
              disabled={uploading}
            >
              {uploading ? (
                <>
                  <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  <span>Uploading to Telegram...</span>
                </>
              ) : (
                "Upload to Drive"
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
