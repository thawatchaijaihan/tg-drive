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

export interface FileMeta {
  v: 1 | 2;
  name: string;
  size: number;
  mime: string;
  uploadedAt: number;
  partIndex?: number;
  totalParts?: number;
  fileGroupId?: string;
  partSize?: number;
}

export function sanitizeFileName(name: string, maxLen = 120): string {
  if (!name || !name.trim()) return `file_${Date.now()}`;
  const lastDot = name.lastIndexOf(".");
  const ext = lastDot !== -1 ? name.slice(lastDot) : "";
  let base = lastDot !== -1 ? name.slice(0, lastDot) : name;
  base = base.replace(/[\\/:*?"<>|\r\n\t]/g, "_").trim();
  base = base.replace(/[. ]+$/, "");
  if (base.length + ext.length > maxLen) {
    const keepLen = maxLen - ext.length - 3;
    base = base.slice(0, Math.max(keepLen, 10)) + "...";
  }
  return base + ext;
}

function parseCaption(caption: string | undefined): FileMeta | null {
  if (!caption) return null;
  try {
    const parsed = JSON.parse(caption);
    if (parsed?.v === 1 || parsed?.v === 2) return parsed as FileMeta;
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
  const rawList: CachedFile[] = [];
  const multiPartGroups = new Map<string, {
    groupId: string;
    name: string;
    totalSize: number;
    mimeType: string;
    date: number;
    parts: { messageId: number; partIndex: number; size: number }[];
  }>();

  for (const msg of messages) {
    if (!msg.media) continue;

    const meta = parseCaption(msg.message);

    // Multi-part grouped files
    if (meta && meta.v === 2 && meta.totalParts && meta.totalParts > 1 && meta.fileGroupId) {
      if (!multiPartGroups.has(meta.fileGroupId)) {
        multiPartGroups.set(meta.fileGroupId, {
          groupId: meta.fileGroupId,
          name: meta.name,
          totalSize: meta.size,
          mimeType: meta.mime,
          date: meta.uploadedAt,
          parts: [],
        });
      }
      multiPartGroups.get(meta.fileGroupId)!.parts.push({
        messageId: msg.id,
        partIndex: meta.partIndex ?? 0,
        size: meta.partSize ?? 0,
      });
      continue;
    }

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
    rawList.push(file);
    await db.files.put(file);
  }

  // Assemble and save multi-part virtual files
  for (const group of multiPartGroups.values()) {
    const sortedParts = group.parts.sort((a, b) => a.partIndex - b.partIndex);
    const primaryId = sortedParts[0]?.messageId || 0;
    const file: CachedFile = {
      id: `${folderId}_grp_${group.groupId}`,
      folderId,
      messageId: primaryId,
      name: group.name,
      size: group.totalSize,
      mimeType: group.mimeType,
      date: group.date,
      mediaRef: "",
      parts: sortedParts,
    };
    rawList.push(file);
    await db.files.put(file);
  }

  rawList.sort((a, b) => b.date - a.date);
  return rawList;
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

export type UploadProgressCallback = (
  pct: number,
  detail?: { speedText?: string; etaText?: string; partText?: string }
) => void;

export async function uploadFile(
  folderId: string,
  file: File,
  onProgress: UploadProgressCallback
): Promise<CachedFile> {
  const client = await getClient();
  const folder = await db.folders.get(folderId);
  if (!folder) throw new Error("Folder or chat not found");

  const peer = toInputPeer(folderId, folder.accessHash, folder.chatType);
  const safeName = sanitizeFileName(file.name);
  const MAX_PART_SIZE = 1900 * 1024 * 1024; // 1.9 GB safe limit

  // Single-part upload (<= 1.9 GB)
  if (file.size <= MAX_PART_SIZE) {
    const startTime = Date.now();
    const uploadedFile = await client.uploadFile({
      file,
      workers: 4,
      onProgress: (pct) => {
        const elapsedSec = (Date.now() - startTime) / 1000;
        let speedText = "";
        let etaText = "";
        if (elapsedSec > 1 && pct > 0) {
          const uploadedBytes = pct * file.size;
          const bytesPerSec = uploadedBytes / elapsedSec;
          speedText = `${formatSize(bytesPerSec)}/s`;
          const remaining = file.size - uploadedBytes;
          const etaSec = Math.round(remaining / bytesPerSec);
          etaText = etaSec > 60 ? `${Math.floor(etaSec / 60)}m ${etaSec % 60}s` : `${etaSec}s`;
        }
        onProgress(pct, { speedText, etaText });
      },
    });

    const captionMeta: FileMeta = {
      v: 2,
      name: safeName,
      size: file.size,
      mime: file.type || "application/octet-stream",
      uploadedAt: Date.now(),
      totalParts: 1,
    };

    const message = await client.sendFile(peer, {
      file: uploadedFile,
      caption: JSON.stringify(captionMeta),
      forceDocument: true,
      workers: 4,
    });

    const cachedFile: CachedFile = {
      id: `${folderId}_${message.id}`,
      folderId,
      messageId: message.id,
      name: safeName,
      size: file.size,
      mimeType: file.type || "application/octet-stream",
      date: Date.now(),
      mediaRef: "",
    };
    await db.files.put(cachedFile);
    return cachedFile;
  }

  // ─── Multi-Part Auto-Chunking (> 1.9 GB) ───
  const totalParts = Math.ceil(file.size / MAX_PART_SIZE);
  const fileGroupId = `grp_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
  const uploadedParts: { messageId: number; partIndex: number; size: number }[] = [];
  const startTime = Date.now();

  for (let i = 0; i < totalParts; i++) {
    const start = i * MAX_PART_SIZE;
    const end = Math.min(start + MAX_PART_SIZE, file.size);
    const partSize = end - start;
    const chunkBlob = file.slice(start, end);
    const chunkFile = new File([chunkBlob], `${safeName}.part${i + 1}`, {
      type: file.type || "application/octet-stream",
    });

    const partProgress = (pct: number) => {
      const partBytes = pct * partSize;
      const totalUploaded = (i * MAX_PART_SIZE) + partBytes;
      const overallPct = totalUploaded / file.size;

      const elapsedSec = (Date.now() - startTime) / 1000;
      let speedText = "";
      let etaText = "";
      if (elapsedSec > 1 && totalUploaded > 0) {
        const bytesPerSec = totalUploaded / elapsedSec;
        speedText = `${formatSize(bytesPerSec)}/s`;
        const remaining = file.size - totalUploaded;
        const etaSec = Math.round(remaining / bytesPerSec);
        etaText = etaSec > 60 ? `${Math.floor(etaSec / 60)}m ${etaSec % 60}s` : `${etaSec}s`;
      }

      onProgress(overallPct, {
        speedText,
        etaText,
        partText: `Part ${i + 1}/${totalParts}`,
      });
    };

    const uploadedPart = await client.uploadFile({
      file: chunkFile,
      workers: 4,
      onProgress: partProgress,
    });

    const captionMeta: FileMeta = {
      v: 2,
      name: safeName,
      size: file.size,
      mime: file.type || "application/octet-stream",
      uploadedAt: Date.now(),
      partIndex: i,
      totalParts,
      fileGroupId,
      partSize,
    };

    const message = await client.sendFile(peer, {
      file: uploadedPart,
      caption: JSON.stringify(captionMeta),
      forceDocument: true,
      workers: 4,
    });

    uploadedParts.push({
      messageId: message.id,
      partIndex: i,
      size: partSize,
    });
  }

  const primaryMessageId = uploadedParts[0].messageId;
  const cachedFile: CachedFile = {
    id: `${folderId}_grp_${fileGroupId}`,
    folderId,
    messageId: primaryMessageId,
    name: safeName,
    size: file.size,
    mimeType: file.type || "application/octet-stream",
    date: Date.now(),
    mediaRef: "",
    parts: uploadedParts,
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

export async function downloadFile(
  file: CachedFile,
  onProgress?: (pct: number) => void
): Promise<void> {
  const client = await getClient();
  const folder = await db.folders.get(file.folderId);
  if (!folder) throw new Error("Folder or chat not found");

  const peer = toInputPeer(file.folderId, folder.accessHash, folder.chatType);

  // Multi-part download
  if (file.parts && file.parts.length > 1) {
    const sorted = [...file.parts].sort((a, b) => a.partIndex - b.partIndex);
    const buffers: ArrayBuffer[] = [];

    for (let i = 0; i < sorted.length; i++) {
      const part = sorted[i];
      const msgs = await client.getMessages(peer, { ids: [part.messageId] });
      if (!msgs[0]?.media) throw new Error(`Part ${i + 1} not found`);

      const data = await client.downloadMedia(msgs[0].media, {
        progressCallback: (downloaded, total) => {
          if (onProgress) {
            const d = Number(downloaded);
            const t = Number(total) || 1;
            const partPct = d / t;
            onProgress((i + partPct) / sorted.length);
          }
        },
      });

      if (!data) throw new Error(`Failed to download part ${i + 1}`);
      const raw = data as unknown as { buffer?: ArrayBuffer; byteOffset?: number; byteLength?: number };
      const ab = raw.buffer
        ? raw.buffer.slice(raw.byteOffset || 0, (raw.byteOffset || 0) + (raw.byteLength || 0))
        : (data as unknown as ArrayBuffer);
      buffers.push(ab);
    }

    const blob = new Blob(buffers, { type: file.mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = file.name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    return;
  }

  // Single file download
  const messages = await client.getMessages(peer, { ids: [file.messageId] });
  if (!messages[0]?.media) throw new Error("File not found on Telegram");

  const data = await client.downloadMedia(messages[0].media, {});
  if (!data) throw new Error("Download failed");

  const raw = data as unknown as { buffer?: ArrayBuffer; byteOffset?: number; byteLength?: number };
  const ab = raw.buffer
    ? raw.buffer.slice(raw.byteOffset || 0, (raw.byteOffset || 0) + (raw.byteLength || 0))
    : (data as unknown as ArrayBuffer);

  const blob = new Blob([ab], { type: file.mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = file.name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

export async function deleteFile(file: CachedFile): Promise<void> {
  const client = await getClient();
  const folder = await db.folders.get(file.folderId);
  if (!folder) throw new Error("Folder or chat not found");

  const peer = toInputPeer(file.folderId, folder.accessHash, folder.chatType);
  const idsToDelete = file.parts && file.parts.length > 0
    ? file.parts.map((p) => p.messageId)
    : [file.messageId];

  await client.deleteMessages(peer, idsToDelete, { revoke: true });
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