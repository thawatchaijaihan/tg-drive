import { useState, useRef } from "react";
import type { DragEvent } from "react";
import { Upload, X, CheckCircle, AlertCircle } from "lucide-react";
import { uploadFile, formatSize } from "../lib/drive";

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
    <dialog className="modal modal-open">
      <div className="modal-box w-full max-w-lg">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-lg">Upload Files</h3>
          <button className="btn btn-ghost btn-sm btn-circle" onClick={onClose} disabled={uploading}>
            <X size={16} />
          </button>
        </div>

        {files.length === 0 && (
          <div
            className={`border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-colors ${
              dragging ? "border-primary bg-primary/5" : "border-base-300 hover:border-primary/50"
            }`}
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
            onClick={() => inputRef.current?.click()}
          >
            <Upload size={32} className="mx-auto mb-3 text-base-content/30" />
            <p className="text-sm text-base-content/60">Drop files here or click to browse</p>
            <p className="text-xs text-base-content/30 mt-1">Auto-splits files &gt; 2 GB • Fast &amp; Unlimited</p>
          </div>
        )}

        {files.length > 0 && (
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {files.map((f, i) => (
              <div key={i} className="bg-base-200 rounded-lg px-4 py-3">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-sm font-medium truncate max-w-[65%]">{f.file.name}</span>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    {f.partText && (
                      <span className="badge badge-info badge-xs font-semibold">{f.partText}</span>
                    )}
                    <span className="text-xs text-base-content/40">{formatSize(f.file.size)}</span>
                    {f.status === "done" && <CheckCircle size={15} className="text-success" />}
                    {f.status === "error" && <AlertCircle size={15} className="text-error" />}
                  </div>
                </div>
                {(f.status === "uploading" || f.status === "done") && (
                  <div>
                    <progress className="progress progress-primary w-full h-1.5" value={f.progress} max={100} />
                    {f.status === "uploading" && (
                      <div className="flex items-center justify-between text-[11px] text-base-content/50 mt-1">
                        <span>{f.progress}%</span>
                        <div className="flex items-center gap-2">
                          {f.speedText && <span className="font-mono text-primary font-medium">{f.speedText}</span>}
                          {f.etaText && <span>ETA: {f.etaText}</span>}
                        </div>
                      </div>
                    )}
                  </div>
                )}
                {f.status === "error" && <p className="text-xs text-error mt-1">{f.error}</p>}
              </div>
            ))}
          </div>
        )}

        {files.length > 0 && !uploading && !allDone && (
          <button className="btn btn-ghost btn-sm mt-3 gap-2" onClick={() => inputRef.current?.click()}>
            <Upload size={14} /> Add more files
          </button>
        )}

        <input
          ref={inputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => addFiles(Array.from(e.target.files ?? []))}
        />

        <div className="modal-action mt-4">
          {allDone ? (
            <button className="btn btn-primary" onClick={onClose}>Done</button>
          ) : (
            <button className="btn btn-primary" onClick={handleUpload} disabled={files.length === 0 || uploading}>
              {uploading ? (
                <><span className="loading loading-spinner loading-sm" /> Uploading…</>
              ) : (
                `Upload${files.length > 0 ? ` ${files.length} file${files.length > 1 ? "s" : ""}` : ""}`
              )}
            </button>
          )}
        </div>
      </div>
      <div className="modal-backdrop" onClick={!uploading ? onClose : undefined} />
    </dialog>
  );
}
