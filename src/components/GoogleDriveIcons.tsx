import {
  FileText,
  FileSpreadsheet,
  FileImage,
  FileVideo,
  FileAudio,
  FileArchive,
  FileCode,
  File,
  Folder,
} from "lucide-react";

export function GoogleDriveLogo({ className = "w-9 h-9" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 87.3 78" xmlns="http://www.w3.org/2000/svg">
      <path d="m6.6 66.85 3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3l13.75-23.8h-27.5c0 1.55.4 3.1 1.2 4.5z" fill="#0066da"/>
      <path d="m43.65 25-13.75-23.8c-1.35.8-2.5 1.9-3.3 3.3l-25.4 44c-.8 1.4-1.2 2.95-1.2 4.5h27.5z" fill="#00ac47"/>
      <path d="m73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5h-27.5l5.85 10.15z" fill="#ea4335"/>
      <path d="m43.65 25 13.75-23.8c-1.35-.8-2.9-1.2-4.5-1.2h-18.5c-1.6 0-3.15.45-4.5 1.2z" fill="#00832d"/>
      <path d="m59.8 53h-32.3l-13.75 23.8c1.35.8 2.9 1.2 4.5 1.2h50.8c1.6 0 3.15-.45 4.5-1.2z" fill="#2684fc"/>
      <path d="m73.4 26.5-12.7-22c-.8-1.4-1.95-2.5-3.3-3.3l-13.75 23.8 16.15 28h27.45c0-1.55-.4-3.1-1.2-4.5z" fill="#ffba00"/>
    </svg>
  );
}

export function GooglePlusIcon({ className = "w-6 h-6" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M12 5V19" stroke="#EA4335" strokeWidth="3.2" strokeLinecap="round" />
      <path d="M5 12H19" stroke="#4285F4" strokeWidth="3.2" strokeLinecap="round" />
      <path d="M12 12H19" stroke="#34A853" strokeWidth="3.2" strokeLinecap="round" />
      <path d="M5 12H12" stroke="#FBBC05" strokeWidth="3.2" strokeLinecap="round" />
    </svg>
  );
}

export function TelegramIcon({ className = "w-5 h-5" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69a.2.2 0 00-.05-.18c-.06-.05-.14-.03-.21-.02-.09.02-1.49.95-4.22 2.79-.4.27-.76.41-1.08.4-.36-.01-1.04-.2-1.55-.37-.63-.2-1.12-.31-1.08-.66.02-.18.27-.36.74-.55 2.92-1.27 4.86-2.11 5.83-2.52 2.77-1.16 3.35-1.36 3.73-1.36.08 0 .27.02.39.12.1.08.13.19.14.27-.01.06.01.24 0 .37z" />
    </svg>
  );
}

export function GoogleFolderIcon({ className = "w-6 h-6", color = "#5f6368" }: { className?: string; color?: string }) {
  return (
    <Folder className={className} fill="currentColor" stroke="none" style={{ color }} />
  );
}

import { getFileCategory } from "../lib/fileCategory";

export function FileIconComponent({
  name,
  mime,
  size = 20,
  className = "",
}: {
  name: string;
  mime?: string;
  size?: number;
  className?: string;
}) {
  const cat = getFileCategory(name, mime);

  switch (cat) {
    case "pdf":
      return <FileText size={size} className={`text-[#ea4335] flex-shrink-0 ${className}`} />;
    case "video":
      return <FileVideo size={size} className={`text-[#d93025] flex-shrink-0 ${className}`} />;
    case "image":
      return <FileImage size={size} className={`text-[#1a73e8] flex-shrink-0 ${className}`} />;
    case "audio":
      return <FileAudio size={size} className={`text-[#f29900] flex-shrink-0 ${className}`} />;
    case "spreadsheet":
      return <FileSpreadsheet size={size} className={`text-[#0f9d58] flex-shrink-0 ${className}`} />;
    case "document":
      return <FileText size={size} className={`text-[#4285f4] flex-shrink-0 ${className}`} />;
    case "archive":
      return <FileArchive size={size} className={`text-[#b06000] flex-shrink-0 ${className}`} />;
    case "code":
      return <FileCode size={size} className={`text-[#188038] flex-shrink-0 ${className}`} />;
    default:
      return <File size={size} className={`text-[#5f6368] dark:text-[#9aa0a6] flex-shrink-0 ${className}`} />;
  }
}
