import { useState, useRef, useEffect } from "react";
import { Search, Folder, X, SlidersHorizontal, ArrowRight } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { searchAll } from "../lib/drive";
import type { SearchResult } from "../lib/drive";
import { FileIconComponent } from "./GoogleDriveIcons";

export default function SearchBar() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      setOpen(false);
      return;
    }
    setLoading(true);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(async () => {
      const res = await searchAll(query);
      setResults(res);
      setOpen(true);
      setLoading(false);
    }, 250);
  }, [query]);

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleSelect = (r: SearchResult) => {
    setQuery("");
    setOpen(false);
    if (r.type === "folder" && r.folder) {
      navigate(`/drive/${r.folder.id}`);
    } else if (r.type === "file" && r.folderId) {
      navigate(`/drive/${r.folderId}`);
    }
  };

  return (
    <div ref={wrapRef} className="relative w-full max-w-2xl">
      {/* Google Drive Pill Search Input */}
      <div
        className={`flex items-center w-full h-11 px-4 rounded-full transition-all duration-200 ${
          open
            ? "bg-white dark:bg-[#1e1f20] shadow-md border border-gray-200 dark:border-gray-700"
            : "bg-[#edf2fc] dark:bg-[#282a2d] hover:bg-[#e1e9f8] dark:hover:bg-[#333538] border border-transparent"
        }`}
      >
        <button
          type="button"
          onClick={() => inputRef.current?.focus()}
          className="text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 mr-3 flex-shrink-0"
          title="Search"
        >
          <Search size={18} />
        </button>

        <input
          ref={inputRef}
          type="text"
          className="w-full bg-transparent text-sm sm:text-base text-gray-800 dark:text-gray-100 placeholder-gray-500 dark:placeholder-gray-400 focus:outline-none"
          placeholder="Search in Drive"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => query.trim() && setOpen(true)}
        />

        {query && (
          <button
            type="button"
            className="p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 rounded-full hover:bg-gray-200 dark:hover:bg-gray-700 mr-1.5 transition-colors"
            onClick={() => {
              setQuery("");
              setOpen(false);
              inputRef.current?.focus();
            }}
            title="Clear search"
          >
            <X size={16} />
          </button>
        )}

        <button
          type="button"
          className="p-1.5 text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 rounded-full hover:bg-gray-200/70 dark:hover:bg-gray-700/70 transition-colors"
          title="Search options"
          onClick={() => inputRef.current?.focus()}
        >
          <SlidersHorizontal size={16} />
        </button>
      </div>

      {/* Dropdown Results */}
      {open && (
        <div className="absolute top-full mt-2 left-0 right-0 bg-white dark:bg-[#1e1f20] border border-gray-200 dark:border-gray-700 rounded-2xl shadow-xl z-50 overflow-hidden max-h-80 overflow-y-auto animate-in fade-in-50 duration-150">
          {loading && (
            <div className="px-5 py-4 text-xs text-gray-500 dark:text-gray-400 flex items-center gap-2.5">
              <span className="w-3.5 h-3.5 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
              Searching in Drive...
            </div>
          )}

          {!loading && results.length === 0 && (
            <div className="px-5 py-6 text-center text-sm text-gray-500 dark:text-gray-400">
              No results found for "<span className="font-medium text-gray-700 dark:text-gray-200">{query}</span>"
            </div>
          )}

          {!loading && results.length > 0 && (
            <ul className="py-2 divide-y divide-gray-100 dark:divide-gray-800">
              {results.map((r, i) => (
                <li key={i}>
                  <button
                    type="button"
                    className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-[#f0f4f9] dark:hover:bg-[#282a2d] transition-colors text-left group"
                    onClick={() => handleSelect(r)}
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      {r.type === "folder" ? (
                        <div className="w-8 h-8 rounded-lg bg-amber-50 dark:bg-amber-950/40 flex items-center justify-center flex-shrink-0 text-amber-500">
                          <Folder size={18} fill="currentColor" stroke="none" />
                        </div>
                      ) : (
                        <div className="w-8 h-8 rounded-lg bg-blue-50 dark:bg-blue-950/40 flex items-center justify-center flex-shrink-0">
                          <FileIconComponent name={r.file?.name || ""} mime={r.file?.mimeType} size={18} />
                        </div>
                      )}
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-gray-800 dark:text-gray-200 truncate group-hover:text-blue-600 dark:group-hover:text-blue-400">
                          {r.type === "folder" ? r.folder?.title : r.file?.name}
                        </p>
                        <p className="text-xs text-gray-400 dark:text-gray-500 truncate">
                          {r.type === "folder" ? "Folder in My Drive" : "File in Telegram Drive"}
                        </p>
                      </div>
                    </div>
                    <ArrowRight size={14} className="text-gray-300 dark:text-gray-600 group-hover:text-blue-500 opacity-0 group-hover:opacity-100 transition-all ml-2 flex-shrink-0" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}