import { useState } from "react";
import { Folder, X } from "lucide-react";
import { createFolder } from "../lib/drive";

interface Props {
  onDone: () => void;
  onClose: () => void;
}

export default function NewFolderModal({ onDone, onClose }: Props) {
  const [name, setName] = useState("Untitled folder");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleCreate = async () => {
    if (!name.trim()) return setError("Enter a folder name.");
    setLoading(true);
    setError("");
    try {
      await createFolder(name.trim());
      onDone();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to create folder.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-xs select-none">
      <div
        className="w-full max-w-sm bg-white dark:bg-[#282a2d] border border-gray-200 dark:border-gray-700 rounded-3xl p-6 shadow-2xl animate-in zoom-in-95 duration-150"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-xl font-normal text-gray-800 dark:text-gray-100 flex items-center gap-2.5">
            <Folder size={22} className="text-[#5f6368] dark:text-[#9aa0a6] fill-current" />
            <span>New folder</span>
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded-full text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        <input
          type="text"
          className="w-full px-4 py-3 rounded-xl border border-gray-300 dark:border-gray-600 bg-white dark:bg-[#1e1f20] text-gray-800 dark:text-gray-100 text-sm focus:outline-none focus:border-[#1a73e8] focus:ring-1 focus:ring-[#1a73e8] transition-all font-sans"
          placeholder="Folder name"
          value={name}
          autoFocus
          onFocus={(e) => e.target.select()}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleCreate()}
        />

        {error && <p className="text-red-500 text-xs mt-2">{error}</p>}

        <div className="flex items-center justify-end gap-2 mt-6">
          <button
            type="button"
            className="px-4 py-2 rounded-full text-sm font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            type="button"
            className="px-5 py-2 rounded-full text-sm font-medium bg-[#1a73e8] hover:bg-[#1557b0] text-white shadow-xs transition-colors flex items-center gap-2 disabled:opacity-60"
            onClick={handleCreate}
            disabled={loading}
          >
            {loading ? (
              <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
            ) : (
              "Create"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
