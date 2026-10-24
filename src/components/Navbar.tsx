import { useState, useRef, useEffect } from "react";
import { LogOut, Sun, Moon, HelpCircle, Settings } from "lucide-react";
import { useAuth } from "../hooks/useAuth";
import { useTheme } from "../context/ThemeContext";
import { useNavigate } from "react-router-dom";
import SearchBar from "./SearchBar";
import { GoogleDriveLogo } from "./GoogleDriveIcons";

export default function Navbar() {
  const { phone, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();
  const [showProfileMenu, setShowProfileMenu] = useState(false);
  const profileMenuRef = useRef<HTMLDivElement>(null);

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (profileMenuRef.current && !profileMenuRef.current.contains(e.target as Node)) {
        setShowProfileMenu(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const initialLetter = phone ? phone.replace(/[^0-9a-zA-Z]/g, "").slice(-2) : "TG";

  return (
    <header className="h-16 px-4 sm:px-6 flex items-center justify-between gap-4 border-b border-gray-200/80 dark:border-gray-800 bg-white/95 dark:bg-[#1e1f20]/95 backdrop-blur z-30 select-none flex-shrink-0">
      {/* Left: Google Drive Logo & Title */}
      <div className="flex items-center gap-3 min-w-[200px]">
        <div
          onClick={() => navigate("/drive")}
          className="flex items-center gap-2.5 cursor-pointer group"
          title="Google Drive (Telegram MTProto)"
        >
          <GoogleDriveLogo className="w-9 h-9 flex-shrink-0 transition-transform group-hover:scale-105 duration-200" />
          <div className="flex items-center gap-1.5">
            <span className="text-[21px] font-medium text-gray-700 dark:text-gray-200 tracking-tight">
              Drive
            </span>
            <span className="bg-[#0088cc] text-white text-[10px] font-bold px-1.5 py-0.5 rounded tracking-wide uppercase shadow-sm">
              Telegram
            </span>
          </div>
        </div>
      </div>

      {/* Center: Search Bar */}
      <div className="flex-1 max-w-2xl hidden md:flex justify-center">
        <SearchBar />
      </div>

      {/* Right: Actions, Theme Toggle & Account Avatar */}
      <div className="flex items-center gap-1.5 sm:gap-2">
        {/* Mobile Search Toggle could be added or SearchBar shown full width on small screens */}
        <div className="flex md:hidden flex-1">
          <SearchBar />
        </div>

        {/* Theme Toggle Button */}
        <button
          type="button"
          onClick={toggleTheme}
          className="w-10 h-10 rounded-full flex items-center justify-center text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          title={theme === "light" ? "Switch to Dark Mode" : "Switch to Light Mode"}
        >
          {theme === "light" ? <Moon size={20} /> : <Sun size={20} className="text-amber-400" />}
        </button>

        {/* Help / Info Button */}
        <button
          type="button"
          onClick={() => window.open("https://github.com/sangketkit01/telegram-drive", "_blank", "noopener,noreferrer")}
          className="w-10 h-10 rounded-full hidden sm:flex items-center justify-center text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          title="About Google Drive (Telegram)"
        >
          <HelpCircle size={20} />
        </button>

        {/* Settings Button */}
        <button
          type="button"
          onClick={() => navigate("/about")}
          className="w-10 h-10 rounded-full hidden sm:flex items-center justify-center text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          title="Settings"
        >
          <Settings size={20} />
        </button>

        {/* Google Workspace Profile Avatar Circle */}
        <div ref={profileMenuRef} className="relative ml-1 sm:ml-2">
          <button
            type="button"
            onClick={() => setShowProfileMenu((prev) => !prev)}
            className="w-10 h-10 rounded-full bg-gradient-to-tr from-blue-600 to-indigo-500 text-white font-medium text-xs sm:text-sm flex items-center justify-center shadow-sm hover:ring-4 hover:ring-blue-100 dark:hover:ring-blue-900/30 transition-all cursor-pointer"
            title="Google / Telegram Account"
          >
            {initialLetter}
          </button>

          {/* Profile Dropdown Menu */}
          {showProfileMenu && (
            <div className="absolute right-0 mt-2 w-72 bg-white dark:bg-[#282a2d] border border-gray-200 dark:border-gray-700 rounded-2xl shadow-xl z-50 p-4 animate-in fade-in-50 duration-150">
              <div className="flex items-center gap-3 pb-3 border-b border-gray-100 dark:border-gray-700">
                <div className="w-12 h-12 rounded-full bg-gradient-to-tr from-blue-600 to-indigo-500 text-white font-medium text-base flex items-center justify-center shadow-inner">
                  {initialLetter}
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-gray-800 dark:text-gray-100 truncate">
                    Telegram Account
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
                    {phone || "Connected MTProto"}
                  </p>
                </div>
              </div>

              <div className="py-2 space-y-1">
                <div className="flex items-center justify-between text-xs py-1.5 px-2 text-gray-600 dark:text-gray-400">
                  <span>Storage Backend</span>
                  <span className="font-semibold text-blue-600 dark:text-blue-400">Telegram Cloud</span>
                </div>
                <div className="flex items-center justify-between text-xs py-1.5 px-2 text-gray-600 dark:text-gray-400">
                  <span>Unlimited Space</span>
                  <span className="text-emerald-600 dark:text-emerald-400 font-semibold">Active</span>
                </div>
              </div>

              <div className="pt-2 border-t border-gray-100 dark:border-gray-700">
                <button
                  type="button"
                  onClick={handleLogout}
                  className="w-full flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30 rounded-xl transition-colors"
                >
                  <LogOut size={16} /> Sign out
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}