import { useState, useRef, useEffect } from "react";
import {
  HardDrive, Folder, Trash2, FolderPlus, Upload, Play,
  ChevronRight, ChevronDown, Cloud
} from "lucide-react";
import type { CachedFolder } from "../lib/db";
import { GooglePlusIcon } from "./GoogleDriveIcons";

interface ChatSidebarProps {
  driveFolders: CachedFolder[];
  chats?: CachedFolder[];
  activeId?: string;
  onSelectChat: (id?: string) => void;
  onNewFolder: () => void;
  onUploadFile?: () => void;
  onImportYouTube?: () => void;
  onDeleteFolder?: (folder: CachedFolder) => void;
  loading?: boolean;
  className?: string;
  onCloseMobile?: () => void;
  onCollapse?: () => void;
}

export default function ChatSidebar({
  driveFolders,
  activeId,
  onSelectChat,
  onNewFolder,
  onUploadFile,
  onImportYouTube,
  onDeleteFolder,
  loading = false,
  className = "",
  onCloseMobile,
}: ChatSidebarProps) {
  const [showNewMenu, setShowNewMenu] = useState(false);
  const [driveExpanded, setDriveExpanded] = useState(true);
  const newMenuRef = useRef<HTMLDivElement>(null);

  // Close "+ New" menu on outside click
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (newMenuRef.current && !newMenuRef.current.contains(e.target as Node)) {
        setShowNewMenu(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const isMyDriveRoot = !activeId || activeId === "root";

  const handleSelect = (id?: string) => {
    onSelectChat(id);
    if (onCloseMobile) onCloseMobile();
  };

  return (
    <aside
      className={`flex flex-col h-full bg-[#f8fafd] dark:bg-[#1e1f20] text-gray-700 dark:text-gray-200 select-none overflow-hidden ${className}`}
    >
      {/* ── Top "+ New" Button Container ── */}
      <div className="p-4 relative" ref={newMenuRef}>
        <button
          type="button"
          onClick={() => setShowNewMenu((prev) => !prev)}
          className="flex items-center gap-3.5 px-5 py-3.5 bg-white dark:bg-[#282a2d] hover:bg-gray-50 dark:hover:bg-[#333538] text-gray-800 dark:text-gray-100 rounded-2xl shadow-[0_1px_3px_0_rgba(60,64,67,0.3),0_4px_8px_3px_rgba(60,64,67,0.15)] hover:shadow-[0_2px_6px_2px_rgba(60,64,67,0.3),0_8px_16px_4px_rgba(60,64,67,0.15)] transition-all duration-200 border border-transparent font-medium text-sm group"
        >
          <GooglePlusIcon className="w-6 h-6 transition-transform group-hover:scale-110 duration-200" />
          <span className="font-medium tracking-wide">New</span>
        </button>

        {/* Dropdown Menu for "+ New" */}
        {showNewMenu && (
          <div className="absolute top-16 left-4 w-60 bg-white dark:bg-[#282a2d] border border-gray-200 dark:border-gray-700 rounded-2xl shadow-xl z-50 py-2 animate-in fade-in-50 duration-150">
            <button
              type="button"
              className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-[#f0f4f9] dark:hover:bg-[#333538] text-sm text-gray-700 dark:text-gray-200 text-left transition-colors"
              onClick={() => {
                setShowNewMenu(false);
                onNewFolder();
              }}
            >
              <FolderPlus size={18} className="text-gray-500 dark:text-gray-400" />
              <span>New folder</span>
            </button>

            {onUploadFile && (
              <>
                <div className="my-1 border-t border-gray-100 dark:border-gray-700" />
                <button
                  type="button"
                  className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-[#f0f4f9] dark:hover:bg-[#333538] text-sm text-gray-700 dark:text-gray-200 text-left transition-colors"
                  onClick={() => {
                    setShowNewMenu(false);
                    onUploadFile();
                  }}
                >
                  <Upload size={18} className="text-gray-500 dark:text-gray-400" />
                  <span>File upload</span>
                </button>
              </>
            )}

            {onImportYouTube && (
              <>
                <div className="my-1 border-t border-gray-100 dark:border-gray-700" />
                <button
                  type="button"
                  className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-red-50 dark:hover:bg-red-950/30 text-sm text-red-600 dark:text-red-400 text-left transition-colors font-medium"
                  onClick={() => {
                    setShowNewMenu(false);
                    onImportYouTube();
                  }}
                >
                  <div className="w-4 h-4 rounded bg-red-600 flex items-center justify-center text-white flex-shrink-0">
                    <Play size={10} className="fill-white translate-x-px" />
                  </div>
                  <span>นำเข้าจาก YouTube (MP4)</span>
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {/* ── Main Drive Folder Tree ── */}
      <div className="flex-1 overflow-y-auto px-2 space-y-1">
        <div>
          <div
            className={`w-full flex items-center gap-2 px-3 py-2.5 rounded-full text-sm font-medium transition-colors ${
              isMyDriveRoot
                ? "bg-[#c2e7ff] text-[#001d35] font-semibold dark:bg-[#004a77] dark:text-[#c2e7ff]"
                : "hover:bg-[#edf2fc] dark:hover:bg-[#282a2d] text-gray-700 dark:text-gray-300"
            }`}
          >
            {driveFolders.length > 0 && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setDriveExpanded((prev) => !prev);
                }}
                className="p-1 rounded-full hover:bg-black/5 dark:hover:bg-white/10"
                title="Expand folders"
              >
                {driveExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              </button>
            )}

            <button
              type="button"
              onClick={() => handleSelect(undefined)}
              className="flex-1 flex items-center gap-2.5 text-left truncate"
            >
              <HardDrive size={18} className="flex-shrink-0" />
              <span className="truncate flex-1">My Drive</span>
              <span className="text-xs px-2 py-0.5 rounded-full bg-gray-200/60 dark:bg-gray-700/60 text-gray-600 dark:text-gray-300">
                {driveFolders.length}
              </span>
            </button>
          </div>

          {/* Subfolders under My Drive */}
          {driveExpanded && driveFolders.length > 0 && (
            <div className="ml-5 pl-2 border-l border-gray-200 dark:border-gray-700 my-1 space-y-0.5">
              {driveFolders.map((folder) => {
                const isActive = activeId === folder.id;
                return (
                  <div key={folder.id} className="group relative flex items-center">
                    <button
                      type="button"
                      onClick={() => handleSelect(folder.id)}
                      className={`w-full flex items-center gap-2.5 px-3 py-1.5 rounded-xl text-xs transition-colors ${
                        isActive
                          ? "bg-[#c2e7ff] text-[#001d35] font-semibold dark:bg-[#004a77] dark:text-[#c2e7ff]"
                          : "hover:bg-[#edf2fc] dark:hover:bg-[#282a2d] text-gray-700 dark:text-gray-300"
                      }`}
                    >
                      <Folder size={15} className="text-amber-500 fill-amber-500 flex-shrink-0" />
                      <span className="truncate flex-1 text-left">{folder.title}</span>
                    </button>

                    {onDeleteFolder && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onDeleteFolder(folder);
                        }}
                        className="opacity-0 group-hover:opacity-100 p-1 text-gray-400 hover:text-red-500 absolute right-2"
                        title="Delete folder"
                      >
                        <Trash2 size={12} />
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* ── Bottom Storage Indicator ── */}
      <div className="p-4 border-t border-gray-200/80 dark:border-gray-800 bg-[#f8fafd] dark:bg-[#1e1f20]">
        <div className="flex items-center gap-2 mb-2 text-xs font-medium text-gray-700 dark:text-gray-300">
          <Cloud size={16} className="text-blue-500 flex-shrink-0" />
          <span className="flex-1">Storage</span>
          <span className="text-[11px] font-semibold text-emerald-600 dark:text-emerald-400 uppercase tracking-wide bg-emerald-50 dark:bg-emerald-950/40 px-2 py-0.5 rounded-full border border-emerald-200 dark:border-emerald-800">
            UNLIMITED
          </span>
        </div>

        {/* Subtle Progress Bar */}
        <div className="w-full bg-gray-200 dark:bg-gray-700 h-1.5 rounded-full overflow-hidden mb-2">
          <div
            className={`bg-gradient-to-r from-blue-500 via-indigo-500 to-sky-400 h-full w-[28%] rounded-full ${
              loading ? "animate-pulse" : ""
            }`}
          />
        </div>

        <p className="text-[11px] text-gray-500 dark:text-gray-400 leading-tight">
          Free Unlimited Telegram MTProto Uncapped
        </p>

        <a
          href="https://t.me"
          target="_blank"
          rel="noreferrer"
          className="mt-3 block text-center text-xs font-medium text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-900/60 rounded-full py-1.5 hover:bg-blue-50 dark:hover:bg-blue-950/30 transition-colors"
        >
          Telegram Cloud Active
        </a>
      </div>
    </aside>
  );
}
