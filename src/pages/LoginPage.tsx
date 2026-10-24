import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { TelegramClient } from "telegram";
import { StringSession } from "telegram/sessions";
import { PromisedWebSockets } from "telegram/extensions/PromisedWebSockets";
import { db } from "../lib/db";
import { useAuth } from "../hooks/useAuth";
import { useTheme } from "../context/ThemeContext";
import {
  KeyRound, Phone, ShieldCheck, Lock,
  ChevronDown, ChevronUp, Sun, Moon,
  Shield, ArrowRight
} from "lucide-react";
import { GoogleDriveLogo } from "../components/GoogleDriveIcons";

type Step = "phone" | "otp" | "password";

export default function LoginPage() {
  const navigate = useNavigate();
  const { refresh } = useAuth();
  const { theme, toggleTheme } = useTheme();

  const [step, setStep] = useState<Step>("phone");
  const [apiId, setApiId] = useState("33156484");
  const [apiHash, setApiHash] = useState("d23bc5cc206aeb76929cb3ff6481a5eb");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [phone, setPhone] = useState("");
  const [otp, setOtp] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const [client, setClient] = useState<TelegramClient | null>(null);
  const [phoneCodeHash, setPhoneCodeHash] = useState("");

  const handlePhone = async () => {
    setError("");
    if (!phone.trim()) {
      return setError("Please enter your Telegram phone number.");
    }
    if (!apiId || !apiHash) {
      return setError("API ID and API Hash are required.");
    }

    setLoading(true);
    try {
      const session = new StringSession("");
      const tgClient = new TelegramClient(session, Number(apiId), apiHash, {
        connectionRetries: 5,
        useWSS: true,
        networkSocket: PromisedWebSockets,
      });
      await tgClient.connect();
      const result = await tgClient.sendCode({ apiId: Number(apiId), apiHash }, phone.trim());
      setPhoneCodeHash(result.phoneCodeHash);
      setClient(tgClient);
      setStep("otp");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to send code to Telegram.");
    } finally {
      setLoading(false);
    }
  };

  const handleOtp = async () => {
    setError("");
    if (!otp.trim()) {
      return setError("Please enter the verification code.");
    }
    setLoading(true);
    try {
      if (!client) throw new Error("Client not initialized");
      await client.invoke(
        new (await import("telegram/tl")).Api.auth.SignIn({
          phoneNumber: phone.trim(),
          phoneCodeHash,
          phoneCode: otp.trim(),
        })
      );
      const sessionString = client.session.save() as unknown as string;
      await db.credentials.put({ id: 1, apiId: Number(apiId), apiHash, sessionString, phone: phone.trim() });
      refresh();
      navigate("/drive");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Invalid code.";
      if (msg.includes("SESSION_PASSWORD_NEEDED")) {
        setError("");
        setStep("password");
      } else {
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  };

  const handlePassword = async () => {
    setError("");
    if (!password) {
      return setError("Please enter your 2FA password.");
    }
    setLoading(true);
    try {
      if (!client) throw new Error("Client not initialized");
      const { computeCheck } = await import("telegram/Password");
      const { Api } = await import("telegram/tl");
      const passwordSrpResult = await client.invoke(new Api.account.GetPassword());
      const passwordSrpCheck = await computeCheck(passwordSrpResult, password);
      await client.invoke(new Api.auth.CheckPassword({ password: passwordSrpCheck }));

      const sessionString = client.session.save() as unknown as string;
      await db.credentials.put({ id: 1, apiId: Number(apiId), apiHash, sessionString, phone: phone.trim() });
      refresh();
      navigate("/drive");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Invalid 2FA password.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#f0f4f9] dark:bg-[#131314] flex flex-col justify-between items-center p-4 sm:p-6 font-sans select-none">
      {/* Top Bar with Theme Toggle */}
      <div className="w-full max-w-4xl flex items-center justify-between py-2">
        <div className="flex items-center gap-2">
          <GoogleDriveLogo className="w-8 h-8" />
          <span className="font-medium text-lg text-gray-700 dark:text-gray-200">
            Drive <span className="text-xs bg-[#0088cc] text-white px-1.5 py-0.5 rounded font-bold uppercase">Telegram</span>
          </span>
        </div>
        <button
          type="button"
          onClick={toggleTheme}
          className="p-2 rounded-full text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 hover:bg-white/80 dark:hover:bg-gray-800 transition-colors"
          title="Toggle theme"
        >
          {theme === "light" ? <Moon size={18} /> : <Sun size={18} className="text-amber-400" />}
        </button>
      </div>

      {/* ── Main Google Sign-In Card ── */}
      <div className="w-full max-w-[440px] my-auto">
        <div className="bg-white dark:bg-[#1e1f20] border border-gray-200 dark:border-gray-800 rounded-[28px] p-8 sm:p-10 shadow-[0_4px_24px_rgba(0,0,0,0.06)] dark:shadow-[0_4px_24px_rgba(0,0,0,0.4)] transition-all">
          {/* Logo & Header */}
          <div className="flex flex-col items-center text-center mb-7">
            <div className="w-14 h-14 rounded-2xl bg-blue-50/70 dark:bg-blue-950/40 flex items-center justify-center mb-4">
              <GoogleDriveLogo className="w-10 h-10" />
            </div>

            <h1 className="text-2xl font-normal text-gray-900 dark:text-gray-100 mb-1">
              Sign in
            </h1>
            <p className="text-sm text-gray-600 dark:text-gray-400">
              to continue to Google Drive (Telegram MTProto)
            </p>
          </div>

          {/* Form Error */}
          {error && (
            <div className="mb-5 p-3 rounded-xl bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 text-xs">
              {error}
            </div>
          )}

          {/* ── Step 1: Phone Number ── */}
          {step === "phone" && (
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                  Telegram Phone Number
                </label>
                <div className="relative">
                  <input
                    type="tel"
                    placeholder="+66 81 234 5678"
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handlePhone()}
                    autoFocus
                    className="w-full px-3.5 py-3 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-[#282a2d] text-gray-800 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:border-[#1a73e8] focus:ring-1 focus:ring-[#1a73e8] transition-all text-sm font-mono"
                  />
                  <Phone size={16} className="absolute right-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
                </div>
                <p className="text-[11px] text-gray-400 mt-1">
                  Include country code (e.g. +66 for Thailand, +1 for US).
                </p>
              </div>

              {/* Advanced API Config Accordion */}
              <div className="pt-1">
                <button
                  type="button"
                  onClick={() => setShowAdvanced((prev) => !prev)}
                  className="flex items-center gap-1.5 text-xs text-[#1a73e8] dark:text-[#8ab4f8] hover:underline"
                >
                  <KeyRound size={13} />
                  <span>Custom Telegram API Credentials</span>
                  {showAdvanced ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                </button>

                {showAdvanced && (
                  <div className="mt-3 p-3.5 bg-gray-50 dark:bg-[#282a2d] rounded-xl border border-gray-200 dark:border-gray-700 space-y-3 animate-in fade-in-50 duration-150">
                    <div>
                      <label className="block text-[11px] text-gray-600 dark:text-gray-400 mb-1">
                        API ID
                      </label>
                      <input
                        type="number"
                        value={apiId}
                        onChange={(e) => setApiId(e.target.value)}
                        className="w-full px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-[#1e1f20] text-xs font-mono"
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] text-gray-600 dark:text-gray-400 mb-1">
                        API Hash
                      </label>
                      <input
                        type="text"
                        value={apiHash}
                        onChange={(e) => setApiHash(e.target.value)}
                        className="w-full px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-[#1e1f20] text-xs font-mono"
                      />
                    </div>
                    <p className="text-[10px] text-gray-400">
                      Default credentials prefilled. You can also generate your own at{" "}
                      <a
                        href="https://my.telegram.org"
                        target="_blank"
                        rel="noreferrer"
                        className="text-blue-500 underline"
                      >
                        my.telegram.org
                      </a>.
                    </p>
                  </div>
                )}
              </div>

              {/* Action Button */}
              <div className="pt-2">
                <button
                  type="button"
                  onClick={handlePhone}
                  disabled={loading}
                  className="w-full py-3 px-4 rounded-full bg-[#1a73e8] hover:bg-[#1557b0] text-white font-medium text-sm shadow-sm hover:shadow transition-all flex items-center justify-center gap-2 disabled:opacity-60 cursor-pointer"
                >
                  {loading ? (
                    <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  ) : (
                    <>
                      <span>Continue</span>
                      <ArrowRight size={15} />
                    </>
                  )}
                </button>
              </div>
            </div>
          )}

          {/* ── Step 2: OTP Verification ── */}
          {step === "otp" && (
            <div className="space-y-4">
              <div className="p-3 bg-blue-50/70 dark:bg-blue-950/40 rounded-xl border border-blue-200 dark:border-blue-900/60 flex items-center gap-2.5">
                <ShieldCheck size={18} className="text-blue-600 dark:text-blue-400 flex-shrink-0" />
                <p className="text-xs text-blue-900 dark:text-blue-200">
                  Verification code sent to your Telegram app for{" "}
                  <span className="font-semibold">{phone}</span>.
                </p>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                  Enter Login Code
                </label>
                <input
                  type="text"
                  maxLength={6}
                  placeholder="· · · · ·"
                  value={otp}
                  onChange={(e) => setOtp(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleOtp()}
                  autoFocus
                  className="w-full px-3.5 py-3 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-[#282a2d] text-gray-800 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:border-[#1a73e8] focus:ring-1 focus:ring-[#1a73e8] transition-all text-center text-xl tracking-widest font-mono"
                />
              </div>

              <div className="flex gap-2.5 pt-2">
                <button
                  type="button"
                  onClick={() => setStep("phone")}
                  className="flex-1 py-2.5 px-4 rounded-full border border-gray-300 dark:border-gray-700 text-gray-700 dark:text-gray-200 text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                >
                  Back
                </button>
                <button
                  type="button"
                  onClick={handleOtp}
                  disabled={loading}
                  className="flex-1 py-2.5 px-4 rounded-full bg-[#1a73e8] hover:bg-[#1557b0] text-white text-sm font-medium shadow-sm transition-all flex items-center justify-center gap-2 disabled:opacity-60"
                >
                  {loading ? (
                    <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  ) : (
                    "Sign In"
                  )}
                </button>
              </div>
            </div>
          )}

          {/* ── Step 3: 2FA Password ── */}
          {step === "password" && (
            <div className="space-y-4">
              <div className="p-3 bg-amber-50/70 dark:bg-amber-950/40 rounded-xl border border-amber-200 dark:border-amber-900/60 flex items-center gap-2.5">
                <Lock size={18} className="text-amber-600 dark:text-amber-400 flex-shrink-0" />
                <p className="text-xs text-amber-900 dark:text-amber-200">
                  Two-step verification active. Enter your Telegram cloud password:
                </p>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                  Telegram Cloud Password
                </label>
                <input
                  type="password"
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handlePassword()}
                  autoFocus
                  className="w-full px-3.5 py-3 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-[#282a2d] text-gray-800 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:border-[#1a73e8] focus:ring-1 focus:ring-[#1a73e8] transition-all text-sm"
                />
              </div>

              <div className="flex gap-2.5 pt-2">
                <button
                  type="button"
                  onClick={() => setStep("otp")}
                  className="flex-1 py-2.5 px-4 rounded-full border border-gray-300 dark:border-gray-700 text-gray-700 dark:text-gray-200 text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                >
                  Back
                </button>
                <button
                  type="button"
                  onClick={handlePassword}
                  disabled={loading}
                  className="flex-1 py-2.5 px-4 rounded-full bg-[#1a73e8] hover:bg-[#1557b0] text-white text-sm font-medium shadow-sm transition-all flex items-center justify-center gap-2 disabled:opacity-60"
                >
                  {loading ? (
                    <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  ) : (
                    "Verify"
                  )}
                </button>
              </div>
            </div>
          )}

          {/* Privacy Guarantee Note */}
          <div className="mt-8 pt-5 border-t border-gray-100 dark:border-gray-800 flex items-start gap-2.5 text-[11px] text-gray-500 dark:text-gray-400">
            <Shield size={14} className="text-emerald-600 dark:text-emerald-400 flex-shrink-0 mt-0.5" />
            <span>
              100% Client-side. Session and encryption keys are stored securely inside your browser's IndexedDB.
            </span>
          </div>
        </div>
      </div>

      {/* ── Google Sign-In Footer ── */}
      <footer className="w-full max-w-4xl flex flex-col sm:flex-row items-center justify-between text-xs text-gray-500 dark:text-gray-400 py-3 gap-2">
        <div className="flex items-center gap-2">
          <span>Google Drive · Telegram Cloud Storage</span>
        </div>

        <div className="flex items-center gap-6">
          <a
            href="https://telegram.org"
            target="_blank"
            rel="noreferrer"
            className="hover:text-gray-800 dark:hover:text-gray-200 transition-colors"
          >
            Telegram MTProto
          </a>
          <button
            type="button"
            onClick={() => navigate("/privacy")}
            className="hover:text-gray-800 dark:hover:text-gray-200 transition-colors"
          >
            Privacy
          </button>
          <button
            type="button"
            onClick={() => navigate("/terms")}
            className="hover:text-gray-800 dark:hover:text-gray-200 transition-colors"
          >
            Terms
          </button>
        </div>
      </footer>
    </div>
  );
}