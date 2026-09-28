import { useState, useEffect, useCallback, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  Folder, FileText, Image, Video, Music, Archive,
  Upload, FolderPlus, Download, Trash2, ChevronLeft,
  RefreshCw, Loader2, Eye, LayoutGrid, List, Share2,
  Menu, Bot, Bookmark, Users, Megaphone, HardDrive, User
} from "lucide-react";
import Navbar from "../components/Navbar";
import ChatSidebar from "../components/ChatSidebar";
import UploadModal from "../components/UploadModal";
import NewFolderModal from "../components/NewFolderModal";
import PreviewModal from "../components/PreviewModal";
import ShareModal from "../components/ShareModal";
import {
  getAllChats, getFiles, downloadFile, deleteFile,
  deleteFolder, formatSize, getThumbnail
} from "../lib/drive";
import type { CachedFile, CachedFolder } from "../lib/db";

function fileIcon(mime: string, size = 16) {
  if (mime.startsWith("image/")) return <Image size={size} className="text-info" />;
  if (mime.startsWith("video/")) return <Video size={size} className="text-secondary" />;
  if (mime.startsWith("audio/")) return <Music size={size} className="text-accent" />;
  if (mime.includes("zip") || mime.includes("tar") || mime.includes("rar"))
    return <Archive size={size} className="text-warning" />;
  return <FileText size={size} className="text-base-content/40" />;
}

// Thumbnail cell — lazy loads from IndexedDB / Telegram
function ThumbCell({ file, onPreview }: { file: CachedFile; onPreview: () => void }) {
  const [thumb, setThumb] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!file.mimeType.startsWith("image/")) return;
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return;
      observer.disconnect();
      getThumbnail(file).then(setThumb).catch(() => {});
    }, { threshold: 0.1 });
    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, [file]);

  return (
    <div
      ref={ref}
      className="w-14 h-14 rounded-lg overflow-hidden bg-base-300 flex items-center justify-center flex-shrink-0 cursor-pointer group-hover:ring-2 ring-primary/30 transition-all"
      onClick={file.mimeType.startsWith("image/") || file.mimeType.startsWith("video/") ? onPreview : undefined}
    >
      {thumb
        ? <img src={thumb} alt="" className="w-full h-full object-cover" />
        : <div className="flex items-center justify-center w-full h-full">
            {fileIcon(file.mimeType, 22)}
          </div>
      }
    </div>
  );
}

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
  const [previewingFile, setPreviewingFile] = useState<CachedFile | null>(null);
  const [sharingFile, setSharingFile] = useState<CachedFile | null>(null);

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

  const canPreview = (f: CachedFile) => f.mimeType.startsWith("image/") || f.mimeType.startsWith("video/");

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
    <div className="min-h-screen bg-base-100 flex flex-col">
      <Navbar />

      {/* Main Two-Pane Layout */}
      <div className="flex-1 flex w-full max-w-[1600px] mx-auto overflow-hidden">
        
        {/* Desktop Sidebar (Left Pane) */}
        <ChatSidebar
          className="w-72 lg:w-80 hidden md:flex flex-shrink-0"
          driveFolders={folders}
          chats={chats}
          activeId={folderId || "root"}
          onSelectChat={(id) => navigate(id ? `/drive/${id}` : "/drive")}
          onNewFolder={() => setShowNewFolder(true)}
          onDeleteFolder={handleDeleteFolder}
          loading={loading}
        />

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
                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3">
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
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
                {files.map((file) => (
                  <div key={file.id} className="group relative bg-base-200/70 border border-base-300/50 rounded-xl overflow-hidden hover:bg-base-200 hover:shadow-md transition-all">
                    {/* Thumbnail area */}
                    <div
                      className="aspect-square flex items-center justify-center bg-base-300/50 cursor-pointer overflow-hidden"
                      onClick={() => canPreview(file) && setPreviewingFile(file)}
                    >
                      {file.mimeType.startsWith("image/")
                        ? <ThumbCell file={file} onPreview={() => setPreviewingFile(file)} />
                        : <div className="flex flex-col items-center gap-2 p-4">
                            {fileIcon(file.mimeType, 32)}
                          </div>
                      }
                    </div>
                    <div className="p-2.5">
                      <p className="text-xs font-medium truncate" title={file.name}>{file.name}</p>
                      <div className="flex items-center justify-between text-[11px] text-base-content/40 mt-0.5">
                        <span>{file.size ? formatSize(file.size) : "—"}</span>
                        <span>{new Date(file.date).toLocaleDateString()}</span>
                      </div>
                    </div>
                    {/* Action overlay */}
                    <div className="absolute top-1.5 right-1.5 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      {canPreview(file) && (
                        <button className="btn btn-xs btn-circle bg-base-100/90 backdrop-blur-sm border-0 shadow-sm" onClick={() => setPreviewingFile(file)} title="Preview">
                          <Eye size={12} />
                        </button>
                      )}
                      <button className="btn btn-xs btn-circle bg-base-100/90 backdrop-blur-sm border-0 text-primary shadow-sm" onClick={() => setSharingFile(file)} title="Share link">
                        <Share2 size={12} />
                      </button>
                      <button className="btn btn-xs btn-circle bg-base-100/90 backdrop-blur-sm border-0 shadow-sm" onClick={() => downloadFile(file)} title="Download">
                        <Download size={12} />
                      </button>
                      <button
                        className="btn btn-xs btn-circle bg-base-100/90 backdrop-blur-sm border-0 text-error shadow-sm"
                        onClick={() => handleDeleteFile(file)}
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
                      <th className="w-14"></th>
                      <th>Name</th>
                      <th className="hidden sm:table-cell">Size</th>
                      <th className="hidden md:table-cell">Date</th>
                      <th className="w-24 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {files.map((file) => (
                      <tr key={file.id} className="hover:bg-base-200/80 border-base-300 group">
                        <td className="py-2">
                          <ThumbCell file={file} onPreview={() => setPreviewingFile(file)} />
                        </td>
                        <td>
                          <span
                            className={`text-sm truncate max-w-[240px] sm:max-w-md block ${canPreview(file) ? "cursor-pointer hover:text-primary transition-colors font-medium" : ""}`}
                            onClick={() => canPreview(file) && setPreviewingFile(file)}
                          >
                            {file.name}
                          </span>
                        </td>
                        <td className="hidden sm:table-cell text-xs text-base-content/50">
                          {file.size ? formatSize(file.size) : "—"}
                        </td>
                        <td className="hidden md:table-cell text-xs text-base-content/50">
                          {new Date(file.date).toLocaleDateString()}
                        </td>
                        <td>
                          <div className="flex items-center justify-end gap-1">
                            {canPreview(file) && (
                              <button className="btn btn-ghost btn-xs btn-circle" onClick={() => setPreviewingFile(file)} title="Preview">
                                <Eye size={13} />
                              </button>
                            )}
                            <button className="btn btn-ghost btn-xs btn-circle text-primary" onClick={() => setSharingFile(file)} title="Share link">
                              <Share2 size={13} />
                            </button>
                            <button className="btn btn-ghost btn-xs btn-circle" onClick={() => downloadFile(file)} title="Download">
                              <Download size={13} />
                            </button>
                            <button
                              className="btn btn-ghost btn-xs btn-circle text-error"
                              onClick={() => handleDeleteFile(file)}
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
      {previewingFile && (
        <PreviewModal
          file={previewingFile}
          onClose={() => setPreviewingFile(null)}
          onDownload={() => { downloadFile(previewingFile); setPreviewingFile(null); }}
        />
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