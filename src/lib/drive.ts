import { Api } from "telegram";
import bigInt from "big-integer";
import { getClient, FOLDER_TAG } from "./telegram";
import { db, pruneThumbCache } from "./db";
import type { CachedFile, CachedFolder } from "./db";

// ─── Helpers ──────────────────────────────────────────────────────────────────

export function formatSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function toInputChannel(id: string, accessHash: string) {
  return new Api.InputChannel({ channelId: bigInt(id), accessHash: bigInt(accessHash) });
}

export function toInputPeer(id: string, accessHash: string, chatType?: string): Api.TypeInputPeer {
  if (id === "self" || chatType === "saved") {
    return new Api.InputPeerSelf();
  }
  if (chatType === "group") {
    return new Api.InputPeerChat({ chatId: bigInt(id) });
  }
  if (chatType === "bot" || chatType === "user") {
    return new Api.InputPeerUser({ userId: bigInt(id), accessHash: bigInt(accessHash || "0") });
  }
  return new Api.InputPeerChannel({ channelId: bigInt(id), accessHash: bigInt(accessHash || "0") });
}

// ─── Metadata caption ─────────────────────────────────────────────────────────

interface FileMeta {
  v: 1;
  name: string;
  size: number;
  mime: string;
  uploadedAt: number;
}

function buildCaption(file: File): string {
  const meta: FileMeta = {
    v: 1,
    name: file.name,
    size: file.size,
    mime: file.type || "application/octet-stream",
    uploadedAt: Date.now(),
  };
  return JSON.stringify(meta);
}

function parseCaption(caption: string | undefined): FileMeta | null {
  if (!caption) return null;
  try {
    const parsed = JSON.parse(caption);
    if (parsed?.v === 1) return parsed as FileMeta;
  } catch {}
  return null;
}

// ─── Folders & Chats ──────────────────────────────────────────────────────────

export async function getAllChats(): Promise<{
  driveFolders: CachedFolder[];
  chats: CachedFolder[];
}> {
  const client = await getClient();
  const dialogs = await client.getDialogs({ limit: 200 });
  const driveFolders: CachedFolder[] = [];
  const chats: CachedFolder[] = [];

  // Always ensure Saved Messages is present
  const savedFolder: CachedFolder = {
    id: "self",
    title: "Saved Messages",
    accessHash: "0",
    createdAt: Date.now(),
    chatType: "saved",
    isTgDriveFolder: false,
  };
  await db.folders.put(savedFolder);
  chats.push(savedFolder);

  for (const dialog of dialogs) {
    const entity = dialog.entity;
    if (!entity) continue;

    const id = entity.id.toString();
    let title = dialog.title || "Untitled";
    const accessHash = (entity as { accessHash?: { toString: () => string } }).accessHash?.toString() ?? "0";
    let chatType: CachedFolder["chatType"] = "user";
    let isTgDriveFolder = false;

    if (entity instanceof Api.User) {
      if (entity.self) {
        continue; // Already added as savedFolder
      } else if (entity.bot) {
        chatType = "bot";
        title = dialog.title || [entity.firstName, entity.lastName].filter(Boolean).join(" ") || entity.username || "Bot";
      } else {
        chatType = "user";
        title = dialog.title || [entity.firstName, entity.lastName].filter(Boolean).join(" ") || entity.username || "Direct Chat";
      }
    } else if (entity instanceof Api.Chat) {
      chatType = "group";
      title = entity.title || "Group";
    } else if (entity instanceof Api.Channel) {
      if (entity.title?.startsWith(FOLDER_TAG)) {
        isTgDriveFolder = true;
        title = entity.title.replace(FOLDER_TAG, "").trim();
        chatType = "folder";
      } else if (entity.megagroup) {
        chatType = "group";
        title = entity.title || "Supergroup";
      } else {
        chatType = "channel";
        title = entity.title || "Channel";
      }
    }

    const folder: CachedFolder = {
      id,
      title,
      accessHash,
      createdAt: dialog.date ? dialog.date * 1000 : Date.now(),
      chatType,
      isTgDriveFolder,
      unreadCount: dialog.unreadCount || 0,
      username: (entity as { username?: string }).username,
    };

    await db.folders.put(folder);

    if (isTgDriveFolder) {
      driveFolders.push(folder);
    } else {
      chats.push(folder);
    }
  }

  return { driveFolders, chats };
}

export async function getFolders(): Promise<CachedFolder[]> {
  const { driveFolders } = await getAllChats();
  return driveFolders;
}

export async function createFolder(name: string): Promise<CachedFolder> {
  const client = await getClient();
  const result = await client.invoke(
    new Api.channels.CreateChannel({
      title: `${FOLDER_TAG} ${name}`,
      about: "Created by TGDrive",
      megagroup: false,
      broadcast: true,
    })
  );

  const chats = (result as Api.Updates).chats;
  if (!chats?.length) throw new Error("Failed to create folder");

  const channel = chats[0] as Api.Channel;
  const folder: CachedFolder = {
    id: channel.id.toString(),
    title: name,
    accessHash: channel.accessHash?.toString() ?? "0",
    createdAt: Date.now(),
    chatType: "folder",
    isTgDriveFolder: true,
  };
  await db.folders.put(folder);
  return folder;
}

export async function deleteFolder(folderId: string): Promise<void> {
  const client = await getClient();
  const folder = await db.folders.get(folderId);
  if (!folder) return;

  if (folder.isTgDriveFolder && folder.accessHash && folder.accessHash !== "0") {
    await client.invoke(
      new Api.channels.DeleteChannel({ channel: toInputChannel(folderId, folder.accessHash) })
    );
  }
  await db.folders.delete(folderId);
  await db.files.where("folderId").equals(folderId).delete();
  const fileIds = (await db.files.where("folderId").equals(folderId).primaryKeys()) as string[];
  await db.thumbs.bulkDelete(fileIds);
}

// ─── Files ────────────────────────────────────────────────────────────────────

export async function getFiles(folderId: string): Promise<CachedFile[]> {
  const client = await getClient();
  const folder = await db.folders.get(folderId);
  if (!folder) throw new Error("Chat or folder not found");

  const peer = toInputPeer(folder.id, folder.accessHash, folder.chatType);
  const messages = await client.getMessages(peer, { limit: 100 });
  const files: CachedFile[] = [];

  for (const msg of messages) {
    if (!msg.media) continue;

    const meta = parseCaption(msg.message);
    let name: string, size: number, mimeType: string, date: number;

    if (meta) {
      name = meta.name; size = meta.size; mimeType = meta.mime; date = meta.uploadedAt;
    } else {
      name = `file_${msg.id}`; size = 0; mimeType = "application/octet-stream"; date = msg.date * 1000;

      if (msg.media instanceof Api.MessageMediaDocument) {
        const doc = msg.media.document;
        if (doc instanceof Api.Document) {
          size = Number(doc.size);
          mimeType = doc.mimeType ?? mimeType;
          const nameAttr = doc.attributes.find(
            (a): a is Api.DocumentAttributeFilename => a instanceof Api.DocumentAttributeFilename
          );
          name = nameAttr?.fileName ?? name;
        }
      } else if (msg.media instanceof Api.MessageMediaPhoto) {
        name = `photo_${msg.id}.jpg`; mimeType = "image/jpeg";
      }
    }

    const file: CachedFile = {
      id: `${folderId}_${msg.id}`,
      folderId, messageId: msg.id, name, size, mimeType, date, mediaRef: "",
    };
    files.push(file);
    await db.files.put(file);
  }
  return files;
}

// ─── Thumbnail ────────────────────────────────────────────────────────────────

export async function getThumbnail(file: CachedFile): Promise<string | null> {
  if (!file.mimeType.startsWith("image/")) return null;

  const cached = await db.thumbs.get(file.id);
  if (cached) return cached.dataUrl;

  const client = await getClient();
  const folder = await db.folders.get(file.folderId);
  if (!folder) return null;

  const peer = toInputPeer(file.folderId, folder.accessHash, folder.chatType);
  const messages = await client.getMessages(peer, { ids: [file.messageId] });
  const msg = messages[0];
  if (!msg?.media) return null;

  try {
    let bestThumbIndex = 0;
    if (msg.media instanceof Api.MessageMediaDocument) {
      const doc = msg.media.document;
      if (doc instanceof Api.Document && doc.thumbs && doc.thumbs.length > 0) {
        let bestArea = 0;
        doc.thumbs.forEach((t, i) => {
          const w = (t as Api.PhotoSize).w ?? 0;
          const h = (t as Api.PhotoSize).h ?? 0;
          if (w * h > bestArea) { bestArea = w * h; bestThumbIndex = i; }
        });
      }
    }

    const data = await client.downloadMedia(
      msg.media,
      { thumb: bestThumbIndex } as Parameters<typeof client.downloadMedia>[1]
    );
    if (!data) return null;

    const raw = data as unknown as { buffer: ArrayBuffer; byteOffset: number; byteLength: number };
    const ab = raw.buffer
      ? raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength)
      : (data as unknown as ArrayBuffer);

    const dataUrl = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(new Blob([ab], { type: "image/jpeg" }));
    });

    await db.thumbs.put({ id: file.id, dataUrl, savedAt: Date.now() });
    pruneThumbCache().catch(() => {});
    return dataUrl;
  } catch {
    return null;
  }
}

// ─── Upload ───────────────────────────────────────────────────────────────────

export async function uploadFile(
  folderId: string,
  file: File,
  onProgress: (pct: number) => void
): Promise<CachedFile> {
  const client = await getClient();
  const folder = await db.folders.get(folderId);
  if (!folder) throw new Error("Folder or chat not found");

  const peer = toInputPeer(folderId, folder.accessHash, folder.chatType);
  const uploadedFile = await client.uploadFile({ file, workers: 4, onProgress });

  const message = await client.sendFile(peer, {
    file: uploadedFile,
    caption: buildCaption(file),
    forceDocument: true,
    workers: 4,
  });

  const cachedFile: CachedFile = {
    id: `${folderId}_${message.id}`,
    folderId, messageId: message.id,
    name: file.name, size: file.size,
    mimeType: file.type || "application/octet-stream",
    date: Date.now(), mediaRef: "",
  };
  await db.files.put(cachedFile);
  return cachedFile;
}

// ─── Preview (images — full blob) ─────────────────────────────────────────────

export async function previewFile(file: CachedFile): Promise<string> {
  const client = await getClient();
  const folder = await db.folders.get(file.folderId);
  if (!folder) throw new Error("Folder or chat not found");

  const peer = toInputPeer(file.folderId, folder.accessHash, folder.chatType);
  const messages = await client.getMessages(peer, { ids: [file.messageId] });
  if (!messages[0]?.media) throw new Error("File not found on Telegram");

  const data = await client.downloadMedia(messages[0].media, {});
  if (!data) throw new Error("Download failed");

  const blob = new Blob([data as ArrayBuffer], { type: file.mimeType });
  return URL.createObjectURL(blob);
}

// ─── Download ─────────────────────────────────────────────────────────────────

export async function downloadFile(file: CachedFile): Promise<void> {
  const client = await getClient();
  const folder = await db.folders.get(file.folderId);
  if (!folder) throw new Error("Folder or chat not found");

  const peer = toInputPeer(file.folderId, folder.accessHash, folder.chatType);
  const messages = await client.getMessages(peer, { ids: [file.messageId] });
  if (!messages[0]?.media) throw new Error("File not found on Telegram");

  const data = await client.downloadMedia(messages[0].media, {});
  if (!data) throw new Error("Download failed");

  const blob = new Blob([data as ArrayBuffer], { type: file.mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = file.name; a.click();
  URL.revokeObjectURL(url);
}

export async function deleteFile(file: CachedFile): Promise<void> {
  const client = await getClient();
  const folder = await db.folders.get(file.folderId);
  if (!folder) throw new Error("Folder or chat not found");

  const peer = toInputPeer(file.folderId, folder.accessHash, folder.chatType);
  await client.deleteMessages(peer, [file.messageId], { revoke: true });
  await db.files.delete(file.id);
  await db.thumbs.delete(file.id);
}

// ─── Search ───────────────────────────────────────────────────────────────────

export interface SearchResult {
  type: "folder" | "file";
  folder?: CachedFolder;
  file?: CachedFile;
  folderId?: string;
}

export async function searchAll(query: string): Promise<SearchResult[]> {
  if (!query.trim()) return [];
  const q = query.toLowerCase();

  const [folders, files] = await Promise.all([
    db.folders.toArray(),
    db.files.toArray(),
  ]);

  const results: SearchResult[] = [];

  for (const folder of folders) {
    if (folder.title.toLowerCase().includes(q)) {
      results.push({ type: "folder", folder });
    }
  }
  for (const file of files) {
    if (file.name.toLowerCase().includes(q)) {
      results.push({ type: "file", file, folderId: file.folderId });
    }
  }
  return results;
}