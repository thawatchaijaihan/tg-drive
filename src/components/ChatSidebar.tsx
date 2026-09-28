import { useState, useMemo } from "react";
import {
  HardDrive, Folder, Bookmark, Bot, Users, Megaphone,
  User, Search, Plus, Trash2, FolderPlus, Sparkles
} from "lucide-react";
import type { CachedFolder } from "../lib/db";

interface ChatSidebarProps {
  driveFolders: CachedFolder[];
  chats: CachedFolder[];
  activeId?: string;
  onSelectChat: (id?: string) => void;
  onNewFolder: () => void;
  onDeleteFolder?: (folder: CachedFolder) => void;
  loading?: boolean;
  className?: string;
  onCloseMobile?: () => void;
}

type FilterTab = "all" | "drive" | "bots" | "groups";

export default function ChatSidebar({
  driveFolders,
  chats,
  activeId,
  onSelectChat,
  onNewFolder,
  onDeleteFolder,
  loading = false,
  className = "",
  onCloseMobile,
}: ChatSidebarProps) {
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState<FilterTab>("all");

  const q = search.trim().toLowerCase();

  // Filter lists
  const filteredDrive = useMemo(() => {
    if (tab === "bots" || tab === "groups") return [];
    if (!q) return driveFolders;
    return driveFolders.filter((f) => f.title.toLowerCase().includes(q));
  }, [driveFolders, q, tab]);

  const filteredChats = useMemo(() => {
    if (tab === "drive") return [];
    let list = chats;
    if (tab === "bots") {
      list = list.filter((c) => c.chatType === "bot");
    } else if (tab === "groups") {
      list = list.filter((c) => c.chatType === "group" || c.chatType === "channel");
    }
    if (!q) return list;
    return list.filter((c) =>
      c.title.toLowerCase().includes(q) ||
      (c.username && c.username.toLowerCase().includes(q))
    );
  }, [chats, q, tab]);

  const bots = useMemo(() => filteredChats.filter((c) => c.chatType === "bot"), [filteredChats]);
  const groups = useMemo(() => filteredChats.filter((c) => c.chatType === "group" || c.chatType === "channel"), [filteredChats]);
  const directChats = useMemo(() => filteredChats.filter((c) => c.chatType === "user"), [filteredChats]);
  const savedMessages = useMemo(() => chats.find((c) => c.chatType === "saved" || c.id === "self"), [chats]);

  const handleSelect = (id?: string) => {
    onSelectChat(id);
    if (onCloseMobile) onCloseMobile();
  };

  const getChatIcon = (c: CachedFolder) => {
    switch (c.chatType) {
      case "saved":
        return <Bookmark size={16} className="text-secondary flex-shrink-0" />;
      case "bot":
        return <Bot size={16} className="text-info flex-shrink-0" />;
      case "group":
        return <Users size={16} className="text-accent flex-shrink-0" />;
      case "channel":
        return <Megaphone size={16} className="text-warning flex-shrink-0" />;
      case "folder":
        return <Folder size={16} className="text-warning flex-shrink-0" />;
      default:
        return <User size={16} className="text-base-content/50 flex-shrink-0" />;
    }
  };

  const isMyDriveActive = !activeId || activeId === "root";

  return (
    <aside className={`flex flex-col bg-base-200/60 border-r border-base-300 h-full select-none ${className}`}>
      {/* Top Header & Search */}
      <div className="p-3 border-b border-base-300 flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Sparkles size={16} className="text-primary" />
            <span className="font-semibold text-xs tracking-wider uppercase text-base-content/70">
              Chats &amp; Folders
            </span>
          </div>
          <button
            className="btn btn-ghost btn-xs gap-1 text-primary hover:bg-primary/10"
            onClick={onNewFolder}
            title="Create new TGDrive folder"
          >
            <FolderPlus size={14} /> New
          </button>
        </div>

        {/* Search */}
        <div className="relative">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-base-content/40" />
          <input
            type="text"
            className="input input-sm input-bordered w-full pl-8 pr-3 text-xs bg-base-100/70 focus:bg-base-100"
            placeholder="Search chats, bots, folders..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        {/* Filter Pills */}
        <div className="flex items-center gap-1 overflow-x-auto no-scrollbar pt-1 text-[11px]">
          <button
            className={`px-2 py-0.5 rounded-full transition-colors ${
              tab === "all" ? "bg-primary text-primary-content font-medium" : "bg-base-300/60 text-base-content/70 hover:bg-base-300"
            }`}
            onClick={() => setTab("all")}
          >
            All
          </button>
          <button
            className={`px-2 py-0.5 rounded-full transition-colors ${
              tab === "drive" ? "bg-primary text-primary-content font-medium" : "bg-base-300/60 text-base-content/70 hover:bg-base-300"
            }`}
            onClick={() => setTab("drive")}
          >
            📁 Drive ({driveFolders.length})
          </button>
          <button
            className={`px-2 py-0.5 rounded-full transition-colors ${
              tab === "bots" ? "bg-primary text-primary-content font-medium" : "bg-base-300/60 text-base-content/70 hover:bg-base-300"
            }`}
            onClick={() => setTab("bots")}
          >
            🤖 Bots
          </button>
          <button
            className={`px-2 py-0.5 rounded-full transition-colors ${
              tab === "groups" ? "bg-primary text-primary-content font-medium" : "bg-base-300/60 text-base-content/70 hover:bg-base-300"
            }`}
            onClick={() => setTab("groups")}
          >
            👥 Groups
          </button>
        </div>
      </div>

      {/* Main List */}
      <div className="flex-1 overflow-y-auto px-2 py-2 space-y-4 text-sm">
        {/* Pinned: My Drive Root & Saved Messages */}
        <div className="space-y-0.5">
          <button
            className={`w-full flex items-center justify-between px-3 py-2 rounded-lg transition-all text-left group ${
              isMyDriveActive
                ? "bg-primary text-primary-content font-medium shadow-sm"
                : "hover:bg-base-300/60 text-base-content"
            }`}
            onClick={() => handleSelect(undefined)}
          >
            <div className="flex items-center gap-2.5 truncate">
              <HardDrive size={16} className={isMyDriveActive ? "text-primary-content" : "text-primary"} />
              <span className="truncate">My Drive</span>
            </div>
            <span
              className={`text-xs px-1.5 py-0.2 rounded-md ${
                isMyDriveActive ? "bg-primary-content/20 text-primary-content" : "bg-base-300 text-base-content/60"
              }`}
            >
              {driveFolders.length}
            </span>
          </button>

          {savedMessages && (
            <button
              className={`w-full flex items-center justify-between px-3 py-2 rounded-lg transition-all text-left ${
                activeId === savedMessages.id
                  ? "bg-primary text-primary-content font-medium shadow-sm"
                  : "hover:bg-base-300/60 text-base-content"
              }`}
              onClick={() => handleSelect(savedMessages.id)}
            >
              <div className="flex items-center gap-2.5 truncate">
                <Bookmark size={16} className={activeId === savedMessages.id ? "text-primary-content" : "text-secondary"} />
                <span className="truncate">{savedMessages.title}</span>
              </div>
              <span className="text-[10px] opacity-70">Saved</span>
            </button>
          )}
        </div>

        {/* Section: TGDrive Folders */}
        {filteredDrive.length > 0 && (
          <div>
            <div className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-base-content/40 flex items-center justify-between">
              <span>📁 TGDrive Folders</span>
              <span>{filteredDrive.length}</span>
            </div>
            <div className="space-y-0.5">
              {filteredDrive.map((folder) => {
                const isActive = activeId === folder.id;
                return (
                  <div
                    key={folder.id}
                    className={`flex items-center justify-between px-3 py-1.5 rounded-lg transition-colors cursor-pointer group ${
                      isActive
                        ? "bg-primary/15 text-primary font-medium ring-1 ring-primary/30"
                        : "hover:bg-base-300/60 text-base-content/80"
                    }`}
                    onClick={() => handleSelect(folder.id)}
                  >
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      <Folder size={15} className={isActive ? "text-primary" : "text-warning"} />
                      <span className="truncate text-xs">{folder.title}</span>
                    </div>
                    {onDeleteFolder && (
                      <button
                        className="btn btn-ghost btn-xs btn-circle opacity-0 group-hover:opacity-100 transition-opacity text-error hover:bg-error/10 h-6 w-6"
                        onClick={(e) => {
                          e.stopPropagation();
                          onDeleteFolder(folder);
                        }}
                        title="Delete folder"
                      >
                        <Trash2 size={12} />
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Section: Bots (e.g. telegram-bot-hub) */}
        {bots.length > 0 && (
          <div>
            <div className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-base-content/40 flex items-center justify-between">
              <span>🤖 Bots &amp; Automations</span>
              <span>{bots.length}</span>
            </div>
            <div className="space-y-0.5">
              {bots.map((bot) => {
                const isActive = activeId === bot.id;
                return (
                  <div
                    key={bot.id}
                    className={`flex items-center justify-between px-3 py-1.5 rounded-lg transition-colors cursor-pointer group ${
                      isActive
                        ? "bg-primary/15 text-primary font-medium ring-1 ring-primary/30"
                        : "hover:bg-base-300/60 text-base-content/80"
                    }`}
                    onClick={() => handleSelect(bot.id)}
                  >
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      <Bot size={15} className={isActive ? "text-primary" : "text-info"} />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-xs font-medium">{bot.title}</p>
                        {bot.username && (
                          <p className="text-[10px] text-base-content/40 truncate">@{bot.username}</p>
                        )}
                      </div>
                    </div>
                    <span className="badge badge-xs badge-info badge-outline text-[9px] px-1 py-0">BOT</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Section: Groups & Channels */}
        {groups.length > 0 && (
          <div>
            <div className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-base-content/40 flex items-center justify-between">
              <span>👥 Groups &amp; Channels</span>
              <span>{groups.length}</span>
            </div>
            <div className="space-y-0.5">
              {groups.map((group) => {
                const isActive = activeId === group.id;
                return (
                  <div
                    key={group.id}
                    className={`flex items-center justify-between px-3 py-1.5 rounded-lg transition-colors cursor-pointer group ${
                      isActive
                        ? "bg-primary/15 text-primary font-medium ring-1 ring-primary/30"
                        : "hover:bg-base-300/60 text-base-content/80"
                    }`}
                    onClick={() => handleSelect(group.id)}
                  >
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      {getChatIcon(group)}
                      <span className="truncate text-xs">{group.title}</span>
                    </div>
                    {group.unreadCount && group.unreadCount > 0 ? (
                      <span className="badge badge-xs badge-primary text-[10px]">{group.unreadCount}</span>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Section: Direct Chats */}
        {directChats.length > 0 && (
          <div>
            <div className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-base-content/40 flex items-center justify-between">
              <span>👤 Direct Chats</span>
              <span>{directChats.length}</span>
            </div>
            <div className="space-y-0.5">
              {directChats.map((chat) => {
                const isActive = activeId === chat.id;
                return (
                  <div
                    key={chat.id}
                    className={`flex items-center justify-between px-3 py-1.5 rounded-lg transition-colors cursor-pointer group ${
                      isActive
                        ? "bg-primary/15 text-primary font-medium ring-1 ring-primary/30"
                        : "hover:bg-base-300/60 text-base-content/80"
                    }`}
                    onClick={() => handleSelect(chat.id)}
                  >
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      <User size={15} className="text-base-content/40" />
                      <span className="truncate text-xs">{chat.title}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Empty state */}
        {!loading && filteredDrive.length === 0 && filteredChats.length === 0 && (
          <div className="text-center py-6 text-base-content/40 text-xs">
            <p>No matching chats or folders</p>
          </div>
        )}
      </div>

      {/* Footer Info */}
      <div className="p-2.5 border-t border-base-300 text-[11px] text-base-content/40 flex items-center justify-between">
        <span>Telegram MTProto</span>
        <button
          className="btn btn-ghost btn-xs text-primary gap-1"
          onClick={onNewFolder}
        >
          <Plus size={12} /> Folder
        </button>
      </div>
    </aside>
  );
}
