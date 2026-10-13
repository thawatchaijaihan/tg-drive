import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  Folder,
  Upload, FolderPlus, Download, Trash2, ChevronLeft,
  RefreshCw, Loader2, LayoutGrid, List, Share2,
  Menu, Bot, Bookmark, Users, Megaphone, HardDrive, User,
  PanelLeftClose, PanelLeftOpen, GripVertical
} from "lucide-react";
import Navbar from "../components/Navbar";
import ChatSidebar from "../components/ChatSidebar";
import UploadModal from "../components/UploadModal";
import NewFolderModal from "../components/NewFolderModal";
import ShareModal from "../components/ShareModal";
import {
  getAllChats, getFiles, downloadFile, deleteFile,
  deleteFolder, formatSize
} from "../lib/drive";
import type { CachedFile, CachedFolder } from "../lib/db";

export default function DrivePage() {
  const { folderId } = useParams<{ folderId?: string }>();
  const navigate = useNavigate();

  const [folders, setFolders] = useState<CachedFolder[]>([]);
  const [chats, setChats] = useState<CachedFolder[]>([]);
  const [files, setFiles] = useState<CachedFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [viewMode, setViewMode] = useState<"list" | "grid">("list");
  const [showMobileSidebar, setShowMobileSidebar] = useState(false);

  const [showUpload, setShowUpload] = useState(false);
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [sharingFile, setSharingFile] = useState<CachedFile | null>(null);

  // Dynamic Resizable & Collapsible Sidebar
  const [sidebarWidth, setSidebarWidth] = useState<number>(() => {
    const saved = localStorage.getItem("tgdrive_sidebar_width");
    return saved ? Math.min(Math.max(Number(saved), 240), 600) : 320;
  });
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState<boolean>(() => {
    return localStorage.getItem("tgdrive_sidebar_collapsed") === "true";
  });
  const [isDragging, setIsDragging] = useState(false);

  const startResizing = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const stopResizing = useCallback(() => {
    setIsDragging(false);
  }, []);

  const resize = useCallback((e: MouseEvent) => {
    if (isDragging) {
      const newWidth = Math.min(Math.max(e.clientX, 240), 600);
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
        setFiles([]);
      } else {
        const fi = await getFiles(folderId);
        setFiles(fi);
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to load.";
      if (msg === "SESSION_EXPIRED" || msg === "NOT_AUTHENTICATED") { navigate("/login"); return; }
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [folderId, navigate]);

  useEffect(() => { load(); }, [load]);

  const handleDeleteFile = async (file: CachedFile) => {
    if (!confirm(`Delete "${file.name}"?`)) return;
    setDeletingId(file.id);
    try {
      await deleteFile(file);
      setFiles((prev) => prev.filter((f) => f.id !== file.id));
    } catch (e: unknown) { alert(e instanceof Error ? e.message : "Delete failed"); }
    finally { setDeletingId(null); }
  };

  const handleDeleteFolder = async (folder: CachedFolder) => {
    if (!confirm(`Delete folder "${folder.title}" and ALL its files?`)) return;
    setDeletingId(folder.id);
    try {
      await deleteFolder(folder.id);
      setFolders((prev) => prev.filter((f) => f.id !== folder.id));
      if (folderId === folder.id) navigate("/drive");
    } catch (e: unknown) { alert(e instanceof Error ? e.message : "Delete failed"); }
    finally { setDeletingId(null); }
  };

  const handleOpenFile = (file: CachedFile) => {
    const isVideoOrAudio = file.mimeType.startsWith("video/") ||
      file.mimeType.startsWith("audio/") ||
      Boolean(file.name.match(/\.(mp4|mkv|webm|mov|avi|m4v|mp3|m4a|flac)$/i));
    if (isVideoOrAudio) {
      window.open(`https://stream.capt-th.work/watch/${file.folderId}/${file.messageId}`, "_blank", "noopener,noreferrer");
    } else {
      downloadFile(file);
    }
  };

  const getChatBadge = (c?: CachedFolder) => {
    if (!c) return null;
    if (c.isTgDriveFolder) return <span className="badge badge-warning badge-sm">TGDrive Folder</span>;
    if (c.chatType === "bot") return <span className="badge badge-info badge-sm">Telegram Bot</span>;
    if (c.chatType === "saved") return <span className="badge badge-secondary badge-sm">Saved Messages</span>;
    if (c.chatType === "group") return <span className="badge badge-accent badge-sm">Group</span>;
    if (c.chatType === "channel") return <span className="badge badge-warning badge-sm">Channel</span>;
    return <span className="badge badge-ghost badge-sm">Chat</span>;
  };

  const getChatHeaderIcon = (c?: CachedFolder) => {
    if (!c || c.isTgDriveFolder) return <Folder size={22} className="text-warning flex-shrink-0" />;
    switch (c.chatType) {
      case "bot": return <Bot size={22} className="text-info flex-shrink-0" />;
      case "saved": return <Bookmark size={22} className="text-secondary flex-shrink-0" />;
      case "group": return <Users size={22} className="text-accent flex-shrink-0" />;
      case "channel": return <Megaphone size={22} className="text-warning flex-shrink-0" />;
      default: return <User size={22} className="text-base-content/50 flex-shrink-0" />;
    }
  };

  return (
    <div className="h-screen bg-base-100 flex flex-col overflow-hidden">
      <Navbar />

      {/* Main Two-Pane Layout */}
      <div className="flex-1 flex w-full overflow-hidden">
        
        {/* Desktop Sidebar (Left Pane) with Dynamic Width */}
        {!isSidebarCollapsed && (
          <div
            style={{ width: `${sidebarWidth}px` }}
            className={`hidden md:flex flex-shrink-0 flex-col h-full relative ${
              isDragging ? "select-none" : "transition-[width] duration-150 ease-out"
            }`}
          >
            <ChatSidebar
              className="w-full h-full border-r border-base-300"
              driveFolders={folders}
              chats={chats}
              activeId={folderId || "root"}
              onSelectChat={(id) => navigate(id ? `/drive/${id}` : "/drive")}
              onNewFolder={() => setShowNewFolder(true)}
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
            className={`hidden md:flex items-center justify-center w-1.5 hover:w-2 cursor-col-resize z-20 group relative select-none transition-all ${
              isDragging ? "bg-primary w-2 shadow-md" : "bg-base-300/60 hover:bg-primary/50"
            }`}
            title="Drag to resize sidebar width"
          >
            <div className="absolute inset-y-0 -left-1 -right-1" />
            <div className="opacity-0 group-hover:opacity-100 transition-opacity">
              <GripVertical size={12} className="text-primary-content" />
            </div>
          </div>
        )}

        {/* Mobile Drawer (Left Pane on Mobile) */}
        {showMobileSidebar && (
          <div className="fixed inset-0 z-50 flex md:hidden">
            <div
              className="fixed inset-0 bg-black/60 backdrop-blur-sm transition-opacity"
              onClick={() => setShowMobileSidebar(false)}
            />
            <div className="relative w-80 max-w-[85vw] h-full z-10 bg-base-200 shadow-2xl animate-in slide-in-from-left duration-200">
              <ChatSidebar
                className="w-full h-full"
                driveFolders={folders}
                chats={chats}
                activeId={folderId || "root"}
                onSelectChat={(id) => navigate(id ? `/drive/${id}` : "/drive")}
                onNewFolder={() => setShowNewFolder(true)}
                onDeleteFolder={handleDeleteFolder}
                loading={loading}
                onCloseMobile={() => setShowMobileSidebar(false)}
              />
            </div>
          </div>
        )}

        {/* Content Area (Right Pane) */}
        <div className="flex-1 min-w-0 flex flex-col px-4 sm:px-6 py-5 overflow-y-auto">
          
          {/* Top Bar: Navigation, Breadcrumb & Actions */}
          <div className="flex items-center justify-between mb-5 gap-3 flex-wrap">
            <div className="flex items-center gap-2 text-sm flex-wrap">
              {/* Mobile Sidebar Toggle Button */}
              <button
                className="btn btn-ghost btn-sm md:hidden gap-1.5 px-2 border border-base-300"
                onClick={() => setShowMobileSidebar(true)}
                title="Open Chats"
              >
                <Menu size={16} />
                <span className="text-xs">Chats</span>
              </button>

              {/* Desktop Sidebar Toggle Button */}
              <button
                className="btn btn-ghost btn-sm hidden md:flex items-center gap-1.5 px-2 border border-base-300 hover:border-primary/50 text-base-content/70 hover:text-base-content"
                onClick={() => setIsSidebarCollapsed((prev) => !prev)}
                title={isSidebarCollapsed ? "Show Sidebar (Ctrl+B)" : "Hide Sidebar (Ctrl+B)"}
              >
                {isSidebarCollapsed ? <PanelLeftOpen size={16} className="text-primary" /> : <PanelLeftClose size={16} />}
                {isSidebarCollapsed && <span className="text-xs">Chats</span>}
              </button>

              <button
                className="font-medium text-base-content/60 hover:text-base-content transition-colors flex items-center gap-1.5"
                onClick={() => navigate("/drive")}
              >
                <HardDrive size={15} /> My Drive
              </button>
              {currentFolder && (
                <>
                  <span className="text-base-content/30">/</span>
                  <div className="flex items-center gap-1.5 font-medium text-base-content">
                    {getChatHeaderIcon(currentFolder)}
                    <span className="truncate max-w-[180px] sm:max-w-[300px]">{currentFolder.title}</span>
                    {getChatBadge(currentFolder)}
                  </div>
                </>
              )}
            </div>

            <div className="flex items-center gap-2">
              {folderId && (
                <div className="flex items-center border border-base-300 rounded-lg overflow-hidden">
                  <button
                    className={`btn btn-ghost btn-xs rounded-none ${viewMode === "list" ? "bg-base-300" : ""}`}
                    onClick={() => setViewMode("list")} title="List view"
                  ><List size={14} /></button>
                  <button
                    className={`btn btn-ghost btn-xs rounded-none ${viewMode === "grid" ? "bg-base-300" : ""}`}
                    onClick={() => setViewMode("grid")} title="Grid view"
                  ><LayoutGrid size={14} /></button>
                </div>
              )}

              <button className="btn btn-ghost btn-sm gap-1.5" onClick={load} disabled={loading}>
                <RefreshCw size={14} className={loading ? "animate-spin" : ""} /> Refresh
              </button>

              {!folderId && (
                <button className="btn btn-primary btn-sm gap-1.5" onClick={() => setShowNewFolder(true)}>
                  <FolderPlus size={14} /> New Folder
                </button>
              )}

              {folderId && (
                <button className="btn btn-primary btn-sm gap-1.5" onClick={() => setShowUpload(true)}>
                  <Upload size={14} /> Upload
                </button>
              )}
            </div>
          </div>

          {folderId && (
            <button className="btn btn-ghost btn-xs gap-1.5 mb-4 text-base-content/60 w-fit" onClick={() => navigate("/drive")}>
              <ChevronLeft size={14} /> Back to My Drive
            </button>
          )}

          {error && (
            <div className="alert alert-error mb-4">
              <span>{error}</span>
              <button className="btn btn-ghost btn-xs" onClick={load}>Retry</button>
            </div>
          )}

          {loading && (
            <div className="flex flex-col items-center justify-center py-20 gap-3 text-base-content/40">
              <Loader2 size={32} className="animate-spin text-primary" />
              <p className="text-xs">Fetching Telegram messages &amp; files...</p>
            </div>
          )}

          {/* Root View — TGDrive folder grid */}
          {!loading && !folderId && (
            folders.length === 0 ? (
              <div className="text-center py-20 text-base-content/40">
                <Folder size={40} className="mx-auto mb-3 opacity-30" />
                <p className="font-medium">No TGDrive folders yet</p>
                <p className="text-sm mt-1">Create a folder or select a chat from the left panel to explore media.</p>
                <button className="btn btn-primary btn-sm mt-4 gap-2" onClick={() => setShowNewFolder(true)}>
                  <FolderPlus size={14} /> Create Folder
                </button>
              </div>
            ) : (
              <div>
                <div className="flex items-center justify-between mb-3 text-xs text-base-content/50 uppercase tracking-wider font-semibold">
                  <span>📁 TGDrive Folders ({folders.length})</span>
                  <span>Select any folder or chat from left sidebar</span>
                </div>
                <div className="grid grid-cols-[repeat(auto-fill,minmax(250px,1fr))] gap-3">
                  {folders.map((folder) => (
                    <div
                      key={folder.id}
                      className="card bg-base-200/80 hover:bg-base-300/80 border border-base-300/60 cursor-pointer transition-all hover:shadow-md group"
                      onClick={() => navigate(`/drive/${folder.id}`)}
                    >
                      <div className="card-body py-4 px-5 flex-row items-center gap-3">
                        <Folder size={26} className="text-warning flex-shrink-0" />
                        <div className="min-w-0 flex-1">
                          <span className="font-medium text-sm block truncate">{folder.title}</span>
                          <span className="text-[11px] text-base-content/40">TGDrive Folder</span>
                        </div>
                        <button
                          className="btn btn-ghost btn-xs btn-circle opacity-0 group-hover:opacity-100 transition-opacity text-error hover:bg-error/10"
                          onClick={(e) => { e.stopPropagation(); handleDeleteFolder(folder); }}
                          disabled={deletingId === folder.id}
                          title="Delete folder"
                        >
                          {deletingId === folder.id
                            ? <span className="loading loading-spinner loading-xs" />
                            : <Trash2 size={13} />}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )
          )}

          {/* Inside Folder or Chat Room */}
          {!loading && folderId && (
            files.length === 0 ? (
              <div className="text-center py-20 text-base-content/40 bg-base-200/30 rounded-2xl border border-dashed border-base-300">
                <Upload size={36} className="mx-auto mb-3 opacity-30" />
                <p className="font-medium">No media or files found</p>
                <p className="text-sm mt-1">This chat or folder doesn't have any photos, videos, or documents yet.</p>
                <button className="btn btn-primary btn-sm mt-4 gap-2" onClick={() => setShowUpload(true)}>
                  <Upload size={14} /> Upload File Here
                </button>
              </div>
            ) : viewMode === "grid" ? (
              /* ── Grid view ── */
              <div className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-3">
                {files.map((file) => (
                  <div
                    key={file.id}
                    onClick={() => handleOpenFile(file)}
                    className="group relative bg-base-200/70 border border-base-300/50 rounded-xl overflow-hidden hover:bg-base-200 hover:shadow-md transition-all cursor-pointer p-3.5"
                    title="Click to stream"
                  >
                    <div className="flex items-center gap-1.5 mb-1.5">
                      <p className="text-xs font-medium truncate flex-1 hover:text-primary transition-colors" title={file.name}>{file.name}</p>
                      {file.parts && file.parts.length > 1 && (
                        <span className="badge badge-info badge-xs flex-shrink-0 font-medium">{file.parts.length}P</span>
                      )}
                    </div>
                    <div className="flex items-center justify-between text-[11px] text-base-content/40 mt-1">
                      <span>{file.size ? formatSize(file.size) : "—"}</span>
                      <span>{new Date(file.date).toLocaleDateString()}</span>
                    </div>
                    {/* Action overlay */}
                    <div className="absolute top-2 right-2 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity" onClick={(e) => e.stopPropagation()}>
                      <button className="btn btn-xs btn-circle bg-base-100/90 backdrop-blur-sm border-0 text-primary shadow-sm" onClick={(e) => { e.stopPropagation(); setSharingFile(file); }} title="Share link">
                        <Share2 size={12} />
                      </button>
                      <button className="btn btn-xs btn-circle bg-base-100/90 backdrop-blur-sm border-0 shadow-sm" onClick={(e) => { e.stopPropagation(); downloadFile(file); }} title="Download">
                        <Download size={12} />
                      </button>
                      <button
                        className="btn btn-xs btn-circle bg-base-100/90 backdrop-blur-sm border-0 text-error shadow-sm"
                        onClick={(e) => { e.stopPropagation(); handleDeleteFile(file); }}
                        disabled={deletingId === file.id}
                        title="Delete"
                      >
                        {deletingId === file.id ? <span className="loading loading-spinner loading-xs" /> : <Trash2 size={12} />}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              /* ── List view ── */
              <div className="overflow-x-auto bg-base-200/40 rounded-xl border border-base-300">
                <table className="table table-sm w-full">
                  <thead>
                    <tr className="text-base-content/50 text-xs border-base-300">
                      <th className="w-12 text-center">#</th>
                      <th>Name</th>
                      <th className="hidden sm:table-cell">Size</th>
                      <th className="hidden md:table-cell">Date</th>
                      <th className="w-24 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {files.map((file, idx) => (
                      <tr
                        key={file.id}
                        onClick={() => handleOpenFile(file)}
                        className="hover:bg-base-200/80 border-base-300 group cursor-pointer transition-colors"
                        title="Click to stream video"
                      >
                        <td className="text-center text-xs text-base-content/40 font-mono select-none">
                          {idx + 1}
                        </td>
                        <td>
                          <div className="flex items-center gap-2">
                            <span className="text-sm truncate max-w-[280px] sm:max-w-md block hover:text-primary transition-colors font-medium">
                              {file.name}
                            </span>
                            {file.parts && file.parts.length > 1 && (
                              <span className="badge badge-info badge-xs flex-shrink-0 font-medium">
                                {file.parts.length} Parts
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="hidden sm:table-cell text-xs text-base-content/50">
                          {file.size ? formatSize(file.size) : "—"}
                        </td>
                        <td className="hidden md:table-cell text-xs text-base-content/50">
                          {new Date(file.date).toLocaleDateString()}
                        </td>
                        <td>
                          <div className="flex items-center justify-end gap-1.5" onClick={(e) => e.stopPropagation()}>
                            <button
                              className="btn btn-ghost btn-xs btn-circle text-primary"
                              onClick={(e) => { e.stopPropagation(); setSharingFile(file); }}
                              title="Share link"
                            >
                              <Share2 size={13} />
                            </button>
                            <button
                              className="btn btn-ghost btn-xs btn-circle"
                              onClick={(e) => { e.stopPropagation(); downloadFile(file); }}
                              title="Download"
                            >
                              <Download size={13} />
                            </button>
                            <button
                              className="btn btn-ghost btn-xs btn-circle text-error"
                              onClick={(e) => { e.stopPropagation(); handleDeleteFile(file); }}
                              disabled={deletingId === file.id}
                              title="Delete"
                            >
                              {deletingId === file.id ? <span className="loading loading-spinner loading-xs" /> : <Trash2 size={13} />}
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          )}
        </div>

      </div>

      {showUpload && folderId && (
        <UploadModal folderId={folderId} onDone={() => { setShowUpload(false); load(); }} onClose={() => setShowUpload(false)} />
      )}
      {showNewFolder && (
        <NewFolderModal onDone={() => { setShowNewFolder(false); load(); }} onClose={() => setShowNewFolder(false)} />
      )}
      {sharingFile && (
        <ShareModal
          file={sharingFile}
          onClose={() => setSharingFile(null)}
        />
      )}
    </div>
  );
}