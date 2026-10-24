import { useState, useEffect, useCallback, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  Folder, Upload, FolderPlus, Download, Trash2, ChevronLeft,
  RefreshCw, Loader2, LayoutGrid, List, Share2, Sparkles, CheckCircle2,
  Menu, Bot, Bookmark, Users, Megaphone, User,
  PanelLeftClose, PanelLeftOpen, ChevronRight, Play
} from "lucide-react";
import Navbar from "../components/Navbar";
import ChatSidebar from "../components/ChatSidebar";
import UploadModal from "../components/UploadModal";
import NewFolderModal from "../components/NewFolderModal";
import ShareModal from "../components/ShareModal";
import YouTubeModal from "../components/YouTubeModal";
import {
  getAllChats, getFiles, downloadFile, deleteFile,
  deleteFolder, formatSize
} from "../lib/drive";
import type { CachedFile, CachedFolder } from "../lib/db";
import { FileIconComponent } from "../components/GoogleDriveIcons";
import { getFileCategory } from "../lib/fileCategory";

type FilterType = "all" | "pdf" | "document" | "spreadsheet" | "image" | "video" | "archive";

const FILTER_CHIPS: { id: FilterType; label: string; icon?: React.ReactNode }[] = [
  { id: "all", label: "All types" },
  { id: "pdf", label: "PDFs" },
  { id: "document", label: "Documents" },
  { id: "spreadsheet", label: "Spreadsheets" },
  { id: "image", label: "Photos & Images" },
  { id: "video", label: "Videos" },
  { id: "archive", label: "Archives" },
];

export default function DrivePage() {
  const { folderId } = useParams<{ folderId?: string }>();
  const navigate = useNavigate();

  const [folders, setFolders] = useState<CachedFolder[]>([]);
  const [chats, setChats] = useState<CachedFolder[]>([]);
  const [files, setFiles] = useState<CachedFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [viewMode, setViewMode] = useState<"list" | "grid">("grid");
  const [selectedFilter, setSelectedFilter] = useState<FilterType>("all");
  const [showMobileSidebar, setShowMobileSidebar] = useState(false);

  const [showUpload, setShowUpload] = useState(false);
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [showYouTubeModal, setShowYouTubeModal] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [convertedIds, setConvertedIds] = useState<number[]>([11]);
  const [sharingFile, setSharingFile] = useState<CachedFile | null>(null);

  // Dynamic Resizable & Collapsible Sidebar
  const [sidebarWidth, setSidebarWidth] = useState<number>(() => {
    const saved = localStorage.getItem("tgdrive_sidebar_width");
    return saved ? Math.min(Math.max(Number(saved), 220), 480) : 260;
  });
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState<boolean>(() => {
    return localStorage.getItem("tgdrive_sidebar_collapsed") === "true";
  });
  const [isDragging, setIsDragging] = useState(false);

  useEffect(() => {
    fetch("https://stream.capt-th.work/api/converted")
      .then((r) => r.json())
      .then((data) => {
        if (Array.isArray(data)) setConvertedIds(data);
      })
      .catch(() => {});
  }, []);

  const startResizing = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const stopResizing = useCallback(() => {
    setIsDragging(false);
  }, []);

  const resize = useCallback((e: MouseEvent) => {
    if (isDragging) {
      const newWidth = Math.min(Math.max(e.clientX, 220), 480);
      setSidebarWidth(newWidth);
      localStorage.setItem("tgdrive_sidebar_width", String(newWidth));
    }
  }, [isDragging]);

  useEffect(() => {
    if (isDragging) {
      window.addEventListener("mousemove", resize);
      window.addEventListener("mouseup", stopResizing);
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    } else {
      window.removeEventListener("mousemove", resize);
      window.removeEventListener("mouseup", stopResizing);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    }
    return () => {
      window.removeEventListener("mousemove", resize);
      window.removeEventListener("mouseup", stopResizing);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
  }, [isDragging, resize, stopResizing]);

  // Persist collapse state
  useEffect(() => {
    localStorage.setItem("tgdrive_sidebar_collapsed", String(isSidebarCollapsed));
  }, [isSidebarCollapsed]);

  // Keyboard shortcut Ctrl+B or Cmd+B to toggle sidebar
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") {
        e.preventDefault();
        setIsSidebarCollapsed((prev) => !prev);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const currentFolder = folders.find((f) => f.id === folderId) || chats.find((c) => c.id === folderId);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const { driveFolders, chats: chatList } = await getAllChats();
      setFolders(driveFolders);
      setChats(chatList);

      if (!folderId) {
        // In root My Drive, load files from default Saved Messages or root if any
        setFiles([]);
      } else {
        const fi = await getFiles(folderId);
        setFiles(fi);
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to load.";
      if (msg === "SESSION_EXPIRED" || msg === "NOT_AUTHENTICATED") {
        navigate("/login");
        return;
      }
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [folderId, navigate]);

  useEffect(() => {
    load();
  }, [load]);

  const handleDeleteFile = async (file: CachedFile) => {
    if (!confirm(`Delete "${file.name}"?`)) return;
    setDeletingId(file.id);
    try {
      await deleteFile(file);
      setFiles((prev) => prev.filter((f) => f.id !== file.id));
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setDeletingId(null);
    }
  };

  const handleDeleteFolder = async (folder: CachedFolder) => {
    if (!confirm(`Delete folder "${folder.title}" and ALL its files?`)) return;
    setDeletingId(folder.id);
    try {
      await deleteFolder(folder.id);
      setFolders((prev) => prev.filter((f) => f.id !== folder.id));
      if (folderId === folder.id) navigate("/drive");
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setDeletingId(null);
    }
  };

  const handleOpenFile = (file: CachedFile) => {
    const isVideoOrAudio =
      file.mimeType.startsWith("video/") ||
      file.mimeType.startsWith("audio/") ||
      Boolean(file.name.match(/\.(mp4|mkv|webm|mov|avi|m4v|mp3|m4a|flac)$/i));
    if (isVideoOrAudio) {
      window.open(
        `https://stream.capt-th.work/watch/${file.folderId}/${file.messageId}`,
        "_blank",
        "noopener,noreferrer"
      );
    } else {
      downloadFile(file);
    }
  };

  const handleOpenColab = async (file: CachedFile) => {
    const streamUrl = `https://stream.capt-th.work/stream/${file.folderId}/${file.messageId}`;
    try {
      await fetch("https://stream.capt-th.work/api/colab/target", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chat_id: file.folderId,
          msg_id: file.messageId,
          title: file.name,
          stream_url: streamUrl,
        }),
      });
    } catch {}
    try {
      await navigator.clipboard.writeText(streamUrl);
    } catch {}
    window.open(
      "https://colab.research.google.com/github/thawatchaijaihan/tg-drive/blob/main/tg_video_faststart_optimizer.ipynb",
      "_blank",
      "noopener,noreferrer"
    );
  };

  // Filter files based on selected category chip
  const filteredFiles = useMemo(() => {
    if (selectedFilter === "all") return files;
    return files.filter((f) => {
      const cat = getFileCategory(f.name, f.mimeType);
      return cat === selectedFilter;
    });
  }, [files, selectedFilter]);

  const getChatHeaderIcon = (c?: CachedFolder) => {
    if (!c || c.isTgDriveFolder) return <Folder size={20} className="text-amber-500 fill-amber-500 flex-shrink-0" />;
    switch (c.chatType) {
      case "bot":
        return <Bot size={20} className="text-cyan-500 flex-shrink-0" />;
      case "saved":
        return <Bookmark size={20} className="text-blue-500 flex-shrink-0" />;
      case "group":
        return <Users size={20} className="text-emerald-500 flex-shrink-0" />;
      case "channel":
        return <Megaphone size={20} className="text-amber-500 flex-shrink-0" />;
      default:
        return <User size={20} className="text-gray-400 flex-shrink-0" />;
    }
  };

  return (
    <div className="h-screen bg-[#f8fafd] dark:bg-[#131314] text-gray-800 dark:text-gray-100 flex flex-col overflow-hidden font-sans">
      <Navbar />

      {/* Main Two-Pane Layout */}
      <div className="flex-1 flex w-full overflow-hidden">
        {/* Desktop Sidebar (Left Pane) */}
        {!isSidebarCollapsed && (
          <div
            style={{ width: `${sidebarWidth}px` }}
            className={`hidden md:flex flex-shrink-0 flex-col h-full relative ${
              isDragging ? "select-none" : "transition-[width] duration-150 ease-out"
            }`}
          >
            <ChatSidebar
              className="w-full h-full border-r border-gray-200/80 dark:border-gray-800"
              driveFolders={folders}
              chats={chats}
              activeId={folderId || "root"}
              onSelectChat={(id) => navigate(id ? `/drive/${id}` : "/drive")}
              onNewFolder={() => setShowNewFolder(true)}
              onUploadFile={() => setShowUpload(true)}
              onImportYouTube={() => setShowYouTubeModal(true)}
              onDeleteFolder={handleDeleteFolder}
              loading={loading}
              onCollapse={() => setIsSidebarCollapsed(true)}
            />
          </div>
        )}

        {/* Resizer Splitter (Drag Handle) */}
        {!isSidebarCollapsed && (
          <div
            onMouseDown={startResizing}
            className={`hidden md:flex items-center justify-center w-1 hover:w-1.5 cursor-col-resize z-20 group relative select-none transition-all ${
              isDragging ? "bg-blue-600 w-1.5" : "bg-transparent hover:bg-blue-400/40"
            }`}
            title="Drag to resize sidebar width"
          >
            <div className="absolute inset-y-0 -left-1 -right-1" />
          </div>
        )}

        {/* Mobile Drawer */}
        {showMobileSidebar && (
          <div className="fixed inset-0 z-50 flex md:hidden">
            <div
              className="fixed inset-0 bg-black/50 backdrop-blur-sm transition-opacity"
              onClick={() => setShowMobileSidebar(false)}
            />
            <div className="relative w-72 max-w-[85vw] h-full z-10 bg-white dark:bg-[#1e1f20] shadow-2xl animate-in slide-in-from-left duration-200">
              <ChatSidebar
                className="w-full h-full"
                driveFolders={folders}
                chats={chats}
                activeId={folderId || "root"}
                onSelectChat={(id) => navigate(id ? `/drive/${id}` : "/drive")}
                onNewFolder={() => setShowNewFolder(true)}
                onUploadFile={() => setShowUpload(true)}
                onImportYouTube={() => setShowYouTubeModal(true)}
                onDeleteFolder={handleDeleteFolder}
                loading={loading}
                onCloseMobile={() => setShowMobileSidebar(false)}
              />
            </div>
          </div>
        )}

        {/* ── Main Content Area (Google Drive Workspace) ── */}
        <div className="flex-1 min-w-0 flex flex-col px-4 sm:px-8 py-4 overflow-y-auto bg-white dark:bg-[#131314] rounded-tl-2xl sm:m-2 sm:ml-0 border border-gray-200/70 dark:border-gray-800 shadow-sm">
          {/* ── Top Header: Breadcrumbs & View Switcher ── */}
          <div className="flex items-center justify-between gap-3 pb-3 border-b border-gray-100 dark:border-gray-800">
            {/* Left: Breadcrumbs / Title */}
            <div className="flex items-center gap-2 text-sm min-w-0">
              {/* Mobile Sidebar Toggle Button */}
              <button
                className="p-1.5 rounded-full hover:bg-gray-100 dark:hover:bg-gray-800 md:hidden text-gray-600 dark:text-gray-300"
                onClick={() => setShowMobileSidebar(true)}
                title="Open Sidebar"
              >
                <Menu size={18} />
              </button>

              {/* Desktop Sidebar Toggle Button */}
              <button
                className="p-1.5 rounded-full hover:bg-gray-100 dark:hover:bg-gray-800 hidden md:flex text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200 transition-colors"
                onClick={() => setIsSidebarCollapsed((prev) => !prev)}
                title={isSidebarCollapsed ? "Show Sidebar (Ctrl+B)" : "Hide Sidebar (Ctrl+B)"}
              >
                {isSidebarCollapsed ? <PanelLeftOpen size={18} className="text-blue-600" /> : <PanelLeftClose size={18} />}
              </button>

              {/* My Drive Title or Breadcrumb */}
              <button
                onClick={() => navigate("/drive")}
                className={`text-lg sm:text-xl font-medium tracking-tight hover:text-blue-600 dark:hover:text-blue-400 transition-colors flex items-center gap-1.5 ${
                  !folderId ? "text-gray-800 dark:text-gray-100" : "text-gray-500 dark:text-gray-400"
                }`}
              >
                My Drive
              </button>

              {currentFolder && (
                <>
                  <ChevronRight size={16} className="text-gray-400 flex-shrink-0" />
                  <div className="flex items-center gap-2 font-medium text-lg sm:text-xl text-gray-800 dark:text-gray-100 truncate">
                    {getChatHeaderIcon(currentFolder)}
                    <span className="truncate max-w-[200px] sm:max-w-[400px]">{currentFolder.title}</span>
                  </div>
                </>
              )}
            </div>

            {/* Right: Actions, Refresh & View Mode */}
            <div className="flex items-center gap-2 flex-shrink-0">
              {/* View Mode Toggle (Google Drive Style) */}
              <div className="flex items-center bg-gray-100 dark:bg-[#282a2d] p-0.5 rounded-full border border-gray-200 dark:border-gray-700">
                <button
                  type="button"
                  onClick={() => setViewMode("list")}
                  className={`p-1.5 rounded-full transition-colors ${
                    viewMode === "list"
                      ? "bg-white dark:bg-[#1e1f20] text-blue-600 shadow-xs"
                      : "text-gray-500 hover:text-gray-800 dark:hover:text-gray-200"
                  }`}
                  title="List layout"
                >
                  <List size={16} />
                </button>
                <button
                  type="button"
                  onClick={() => setViewMode("grid")}
                  className={`p-1.5 rounded-full transition-colors ${
                    viewMode === "grid"
                      ? "bg-white dark:bg-[#1e1f20] text-blue-600 shadow-xs"
                      : "text-gray-500 hover:text-gray-800 dark:hover:text-gray-200"
                  }`}
                  title="Grid layout"
                >
                  <LayoutGrid size={16} />
                </button>
              </div>

              {/* Refresh Button */}
              <button
                type="button"
                onClick={load}
                disabled={loading}
                className="p-2 rounded-full hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 transition-colors"
                title="Refresh"
              >
                <RefreshCw size={16} className={loading ? "animate-spin text-blue-600" : ""} />
              </button>

              {/* YouTube Import Button */}
              <button
                type="button"
                onClick={() => setShowYouTubeModal(true)}
                className="flex items-center gap-1.5 bg-red-600 hover:bg-red-700 text-white text-xs sm:text-sm font-medium px-3 sm:px-3.5 py-2 rounded-full shadow-sm hover:shadow transition-all"
                title="นำเข้าวิดีโอจาก YouTube เป็น MP4"
              >
                <Play size={13} className="fill-white translate-x-0.5" />
                <span className="hidden sm:inline">นำเข้า YouTube</span>
              </button>

              {/* Upload or New Folder button */}
              {folderId ? (
                <button
                  onClick={() => setShowUpload(true)}
                  className="flex items-center gap-2 bg-[#1a73e8] hover:bg-[#1557b0] text-white text-xs sm:text-sm font-medium px-4 py-2 rounded-full shadow-sm hover:shadow transition-all"
                >
                  <Upload size={14} /> Upload
                </button>
              ) : (
                <button
                  onClick={() => setShowNewFolder(true)}
                  className="flex items-center gap-2 bg-[#1a73e8] hover:bg-[#1557b0] text-white text-xs sm:text-sm font-medium px-4 py-2 rounded-full shadow-sm hover:shadow transition-all"
                >
                  <FolderPlus size={14} /> New Folder
                </button>
              )}
            </div>
          </div>

          {/* ── Filter Chips Bar (As shown in user's Google Drive reference) ── */}
          <div className="flex items-center gap-2 py-3 overflow-x-auto no-scrollbar select-none">
            {FILTER_CHIPS.map((chip) => {
              const isActive = selectedFilter === chip.id;
              return (
                <button
                  key={chip.id}
                  onClick={() => setSelectedFilter(chip.id)}
                  className={`px-3.5 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-all border ${
                    isActive
                      ? "bg-[#c2e7ff] text-[#001d35] border-transparent font-semibold dark:bg-[#004a77] dark:text-[#c2e7ff]"
                      : "bg-white dark:bg-[#202124] text-gray-700 dark:text-gray-300 border-gray-300 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-[#282a2d]"
                  }`}
                >
                  {chip.label}
                </button>
              );
            })}
          </div>

          {/* Back button when inside folder */}
          {folderId && (
            <div className="mb-3">
              <button
                onClick={() => navigate("/drive")}
                className="inline-flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 transition-colors"
              >
                <ChevronLeft size={14} /> Back to My Drive
              </button>
            </div>
          )}

          {/* Error Alert */}
          {error && (
            <div className="p-3 mb-4 rounded-xl bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 text-sm flex items-center justify-between">
              <span>{error}</span>
              <button onClick={load} className="text-xs font-semibold underline ml-2">Retry</button>
            </div>
          )}

          {/* Loading Indicator */}
          {loading && (
            <div className="flex flex-col items-center justify-center py-24 gap-3 text-gray-400">
              <Loader2 size={36} className="animate-spin text-blue-600" />
              <p className="text-xs">Fetching Google Drive &amp; Telegram items...</p>
            </div>
          )}

          {/* ── ROOT VIEW: Folders Section ── */}
          {!loading && !folderId && (
            <div className="space-y-6">
              {/* Folders Section */}
              <div>
                <div className="flex items-center justify-between mb-3">
                  <h2 className="text-xs font-semibold text-gray-500 dark:text-gray-400 tracking-wider uppercase">
                    Folders ({folders.length})
                  </h2>
                </div>

                {folders.length === 0 ? (
                  <div className="text-center py-16 border-2 border-dashed border-gray-200 dark:border-gray-800 rounded-2xl">
                    <Folder size={44} className="mx-auto mb-3 text-gray-300 dark:text-gray-600" />
                    <p className="font-medium text-gray-700 dark:text-gray-300 text-sm">No folders in My Drive yet</p>
                    <p className="text-xs text-gray-400 mt-1 max-w-sm mx-auto">
                      Click "+ New" to create your first cloud folder, or pick any chat from the left sidebar to explore Telegram media.
                    </p>
                    <button
                      onClick={() => setShowNewFolder(true)}
                      className="mt-4 inline-flex items-center gap-2 bg-[#1a73e8] hover:bg-[#1557b0] text-white text-xs font-medium px-4 py-2 rounded-full shadow-sm"
                    >
                      <FolderPlus size={14} /> New Folder
                    </button>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                    {folders.map((folder) => (
                      <div
                        key={folder.id}
                        onClick={() => navigate(`/drive/${folder.id}`)}
                        className="group relative flex items-center justify-between p-3.5 bg-[#f0f4f9] dark:bg-[#202124] hover:bg-[#e1e9f8] dark:hover:bg-[#282a2d] border border-gray-200/60 dark:border-gray-800 rounded-xl transition-all duration-150 cursor-pointer shadow-xs hover:shadow"
                      >
                        <div className="flex items-center gap-3 min-w-0">
                          <Folder size={22} className="text-[#5f6368] dark:text-[#9aa0a6] fill-current flex-shrink-0" />
                          <span className="text-sm font-medium text-gray-800 dark:text-gray-200 truncate">
                            {folder.title}
                          </span>
                        </div>

                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDeleteFolder(folder);
                          }}
                          disabled={deletingId === folder.id}
                          className="opacity-0 group-hover:opacity-100 p-1.5 rounded-full hover:bg-red-100 dark:hover:bg-red-900/40 text-gray-400 hover:text-red-600 transition-all"
                          title="Delete folder"
                        >
                          {deletingId === folder.id ? (
                            <span className="w-3 h-3 border-2 border-red-500 border-t-transparent rounded-full animate-spin" />
                          ) : (
                            <Trash2 size={14} />
                          )}
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ── FOLDER / CHAT VIEW: Files Section ── */}
          {!loading && folderId && (
            <div>
              <div className="flex items-center justify-between mb-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                <span>Files ({filteredFiles.length})</span>
                {selectedFilter !== "all" && (
                  <span className="text-blue-600 dark:text-blue-400 normal-case">
                    Filtered by: {selectedFilter}
                  </span>
                )}
              </div>

              {filteredFiles.length === 0 ? (
                <div className="text-center py-20 border-2 border-dashed border-gray-200 dark:border-gray-800 rounded-2xl">
                  <Upload size={40} className="mx-auto mb-3 text-gray-300 dark:text-gray-600" />
                  <p className="font-medium text-gray-700 dark:text-gray-300 text-sm">
                    {files.length === 0
                      ? "No files in this folder yet"
                      : `No files matching "${selectedFilter}"`}
                  </p>
                  <p className="text-xs text-gray-400 mt-1">
                    Upload photos, videos, or documents directly to Telegram MTProto storage.
                  </p>
                  <button
                    onClick={() => setShowUpload(true)}
                    className="mt-4 inline-flex items-center gap-2 bg-[#1a73e8] hover:bg-[#1557b0] text-white text-xs font-medium px-4 py-2 rounded-full shadow-sm"
                  >
                    <Upload size={14} /> Upload File
                  </button>
                </div>
              ) : viewMode === "grid" ? (
                /* ── Google Drive Grid View ── */
                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
                  {filteredFiles.map((file) => {
                    const isVideo =
                      file.mimeType.startsWith("video/") ||
                      Boolean(file.name.match(/\.(mp4|mkv|webm|mov|avi|m4v|flac)$/i));
                    const isConverted =
                      Boolean(file.isConverted) ||
                      convertedIds.includes(file.messageId) ||
                      file.name.toLowerCase().includes("faststart");

                    return (
                      <div
                        key={file.id}
                        onClick={() => handleOpenFile(file)}
                        className="group relative flex flex-col bg-[#f0f4f9] dark:bg-[#1e1f20] hover:bg-[#e1e9f8] dark:hover:bg-[#282a2d] border border-gray-200/70 dark:border-gray-800 rounded-2xl overflow-hidden cursor-pointer transition-all duration-200 hover:shadow-md"
                      >
                        {/* Preview Header Area */}
                        <div className="h-28 w-full bg-white/70 dark:bg-[#282a2d]/70 flex items-center justify-center relative overflow-hidden border-b border-gray-100 dark:border-gray-800">
                          <FileIconComponent
                            name={file.name}
                            mime={file.mimeType}
                            size={44}
                            className="transition-transform group-hover:scale-110 duration-200"
                          />

                          {/* Video Play Badge if Video */}
                          {isVideo && (
                            <div className="absolute inset-0 bg-black/20 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                              <div className="w-10 h-10 rounded-full bg-black/60 text-white flex items-center justify-center shadow-lg">
                                <Play size={18} className="fill-white ml-0.5" />
                              </div>
                            </div>
                          )}

                          {/* Top-Right Quick Action Buttons */}
                          <div
                            className="absolute top-2 right-2 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity bg-white/90 dark:bg-[#1e1f20]/90 backdrop-blur-sm p-1 rounded-full shadow-sm"
                            onClick={(e) => e.stopPropagation()}
                          >
                            {/* Colab Optimize button for video */}
                            {isVideo && (
                              isConverted ? (
                                <span
                                  className="p-1 rounded-full text-emerald-500"
                                  title="FastStart Optimized"
                                >
                                  <CheckCircle2 size={14} />
                                </span>
                              ) : (
                                <button
                                  type="button"
                                  onClick={() => handleOpenColab(file)}
                                  className="p-1 rounded-full text-amber-500 hover:bg-amber-100 dark:hover:bg-amber-950/40"
                                  title="Optimize on Colab"
                                >
                                  <Sparkles size={14} className="animate-pulse" />
                                </button>
                              )
                            )}

                            <button
                              type="button"
                              onClick={() => setSharingFile(file)}
                              className="p-1 rounded-full text-blue-600 hover:bg-blue-100 dark:hover:bg-blue-950/40"
                              title="Share"
                            >
                              <Share2 size={14} />
                            </button>

                            <button
                              type="button"
                              onClick={() => downloadFile(file)}
                              className="p-1 rounded-full text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700"
                              title="Download"
                            >
                              <Download size={14} />
                            </button>

                            <button
                              type="button"
                              onClick={() => handleDeleteFile(file)}
                              disabled={deletingId === file.id}
                              className="p-1 rounded-full text-red-500 hover:bg-red-100 dark:hover:bg-red-950/40"
                              title="Delete"
                            >
                              <Trash2 size={14} />
                            </button>
                          </div>
                        </div>

                        {/* File Details Bottom */}
                        <div className="p-3">
                          <div className="flex items-center gap-2 mb-1">
                            <FileIconComponent
                              name={file.name}
                              mime={file.mimeType}
                              size={16}
                            />
                            <p
                              className="text-xs font-medium text-gray-800 dark:text-gray-200 truncate flex-1 group-hover:text-blue-600 dark:group-hover:text-blue-400"
                              title={file.name}
                            >
                              {file.name}
                            </p>
                          </div>
                          <div className="flex items-center justify-between text-[11px] text-gray-400 dark:text-gray-500">
                            <span>{formatSize(file.size)}</span>
                            <span>{new Date(file.date).toLocaleDateString()}</span>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                /* ── Google Drive List View ── */
                <div className="overflow-x-auto border border-gray-200 dark:border-gray-800 rounded-2xl">
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr className="border-b border-gray-200 dark:border-gray-800 text-xs font-medium text-gray-500 dark:text-gray-400 bg-gray-50/50 dark:bg-[#1e1f20]/50">
                        <th className="py-3 px-4">Name</th>
                        <th className="py-3 px-4 hidden sm:table-cell">Owner</th>
                        <th className="py-3 px-4 hidden md:table-cell">Last modified</th>
                        <th className="py-3 px-4">File size</th>
                        <th className="py-3 px-4 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                      {filteredFiles.map((file) => {
                        const isVideo =
                          file.mimeType.startsWith("video/") ||
                          Boolean(file.name.match(/\.(mp4|mkv|webm|mov|avi|m4v|flac)$/i));
                        const isConverted =
                          Boolean(file.isConverted) ||
                          convertedIds.includes(file.messageId) ||
                          file.name.toLowerCase().includes("faststart");

                        return (
                          <tr
                            key={file.id}
                            onClick={() => handleOpenFile(file)}
                            className="group hover:bg-[#edf2fc] dark:hover:bg-[#282a2d] transition-colors cursor-pointer"
                          >
                            <td className="py-3 px-4">
                              <div className="flex items-center gap-3">
                                <FileIconComponent
                                  name={file.name}
                                  mime={file.mimeType}
                                  size={18}
                                />
                                <span
                                  className="text-xs sm:text-sm font-medium text-gray-800 dark:text-gray-200 truncate max-w-xs sm:max-w-md group-hover:text-blue-600 dark:group-hover:text-blue-400"
                                  title={file.name}
                                >
                                  {file.name}
                                </span>
                              </div>
                            </td>
                            <td className="py-3 px-4 hidden sm:table-cell text-xs text-gray-500">
                              Telegram
                            </td>
                            <td className="py-3 px-4 hidden md:table-cell text-xs text-gray-500">
                              {new Date(file.date).toLocaleDateString()}
                            </td>
                            <td className="py-3 px-4 text-xs text-gray-500">
                              {formatSize(file.size)}
                            </td>
                            <td className="py-3 px-4 text-right" onClick={(e) => e.stopPropagation()}>
                              <div className="flex items-center justify-end gap-1">
                                {isVideo && (
                                  isConverted ? (
                                    <span
                                      className="p-1 text-emerald-500"
                                      title="FastStart Ready"
                                    >
                                      <CheckCircle2 size={15} />
                                    </span>
                                  ) : (
                                    <button
                                      type="button"
                                      onClick={() => handleOpenColab(file)}
                                      className="p-1 rounded-full text-amber-500 hover:bg-amber-100 dark:hover:bg-amber-950/40"
                                      title="Optimize on Google Colab"
                                    >
                                      <Sparkles size={15} className="animate-pulse" />
                                    </button>
                                  )
                                )}

                                <button
                                  type="button"
                                  onClick={() => setSharingFile(file)}
                                  className="p-1.5 rounded-full text-gray-500 hover:text-blue-600 hover:bg-gray-100 dark:hover:bg-gray-800"
                                  title="Share link"
                                >
                                  <Share2 size={15} />
                                </button>

                                <button
                                  type="button"
                                  onClick={() => downloadFile(file)}
                                  className="p-1.5 rounded-full text-gray-500 hover:text-gray-800 hover:bg-gray-100 dark:hover:bg-gray-800"
                                  title="Download"
                                >
                                  <Download size={15} />
                                </button>

                                <button
                                  type="button"
                                  onClick={() => handleDeleteFile(file)}
                                  disabled={deletingId === file.id}
                                  className="p-1.5 rounded-full text-gray-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950/40"
                                  title="Delete"
                                >
                                  <Trash2 size={15} />
                                </button>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── Modals ── */}
      {showUpload && folderId && (
        <UploadModal
          folderId={folderId}
          onDone={() => {
            setShowUpload(false);
            load();
          }}
          onClose={() => setShowUpload(false)}
        />
      )}

      {showNewFolder && (
        <NewFolderModal
          onDone={() => {
            setShowNewFolder(false);
            load();
          }}
          onClose={() => setShowNewFolder(false)}
        />
      )}

      {sharingFile && (
        <ShareModal
          file={sharingFile}
          onClose={() => setSharingFile(null)}
        />
      )}

      {showYouTubeModal && (
        <YouTubeModal
          folderId={folderId || "3525937661"}
          folderTitle={currentFolder?.title || "YouTube"}
          onDone={load}
          onClose={() => setShowYouTubeModal(false)}
        />
      )}
    </div>
  );
}