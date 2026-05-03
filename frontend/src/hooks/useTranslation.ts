/**
 * Translation hook — fetches Dutch translations from the backend
 * and provides a `t(key)` helper that falls back to English.
 */
import { useCallback, useEffect, useState } from "react";

// English fallback strings (same keys as backend UI_STRINGS)
const EN: Record<string, string> = {
  // Navigation
  "ui.blog": "Blog",
  "ui.projects": "Projects",
  "ui.about": "About",
  "ui.linkedin": "LinkedIn",
  "ui.github": "GitHub",
  "ui.email": "Email",
  "ui.about_arrow": "About ↓",

  // Settings
  "ui.light_mode": "Light mode",
  "ui.dark_mode": "Dark mode",
  "ui.switch_to_english": "Switch to English",
  "ui.switch_to_dutch": "Switch to Dutch",
  "ui.speak_replies": "Speak replies",
  "ui.voice": "Voice",
  "ui.clear_conversation": "Clear conversation",

  // Chat
  "ui.ask_placeholder": "Ask about Sebastiaan…",
  "ui.ask_anything": "Ask me anything!",
  "ui.tell_me_about": "Tell me about",
  "ui.conversation_ended": "Conversation ended.",
  "ui.new_conversation": "New conversation",
  "ui.session_end_message": "That's the end of this session. Start a new one to keep chatting.",
  "ui.thinking": "Thinking…",
  "ui.transcribing": "Transcribing…",
  "ui.stop_recording": "Stop recording",
  "ui.speak_question": "Speak your question",
  "ui.recording": "recording",
  "ui.scroll_for_more": "scroll for more",
  "ui.play": "▶︎ play",
  "ui.copy": "⎘ copy",
  "ui.copied": "✓ copied",
  "ui.send": "Send",
  "ui.back_to_home": "Back to home",
  "ui.settings": "Settings",

  // Hero
  "ui.subtitle": "Creative adventurer. Nerd with MBA.",

  // About
  "about.heading": "About",
  "about.hi": "Hi, I'm Sebastiaan",
  "about.p1": "Director of Data Science & AI by day, compulsive builder by night. I lead teams that turn messy data into decisions that actually matter — from fraud detection to supply chain optimisation.",
  "about.p2": "When I'm not wrangling models, I'm building furniture from scratch (full kitchen, done), running (slowly), or hosting overly competitive board game nights.",
  "about.p3_prefix": "This site is my digital twin — an AI agent trained on my professional and personal knowledge. Ask",
  "about.p3_suffix": "anything, or explore the mind map above.",
  "about.footer": "Built with too many Docker containers",

  // Section headers
  "ui.the_curiosa": "The Curiosa",
  "ui.projects_heading": "Projects",
  "ui.more_posts_coming": "More posts coming soon",

  // Chat welcome + chips
  "chat.welcome": "Hey! I'm Sebastiaan's digital twin. Ask me about my experience, projects, or how I think about AI.",
  "chat.chip.career_arc": "Career arc",
  "chat.chip.career_arc_text": "Give me a quick summary of your career arc.",
  "chat.chip.side_projects": "Side projects",
  "chat.chip.side_projects_text": "What are your most interesting side projects?",
  "chat.chip.ai_perspective": "AI perspective",
  "chat.chip.ai_perspective_text": "How do you think about AI and its role?",
  "chat.chip.tech_stack": "Tech stack",
  "chat.chip.tech_stack_text": "What's your preferred tech stack and why?",
};

export type TranslateFunc = (key: string, fallback?: string) => string;

/** Translate a node title: look up `node.<id>` in translations, fall back to original title */
export type TranslateNodeFunc = (nodeId: string, originalTitle: string) => string;

export interface UseTranslationReturn {
  t: TranslateFunc;
  tn: TranslateNodeFunc;
  ready: boolean;
  language: "nl" | "en" | null;
}

export function useTranslation(
  language: "nl" | "en" | null,
  token?: string,
): UseTranslationReturn {
  const [nlStrings, setNlStrings] = useState<Record<string, string>>({});
  const [ready, setReady] = useState(language !== "nl");

  useEffect(() => {
    if (language !== "nl") {
      setReady(true);
      return;
    }

    const headers: Record<string, string> = {};
    if (token) headers["X-Access-Token"] = token;

    fetch("/api/translations?lang=nl", { headers })
      .then((r) => r.json())
      .then((data: Record<string, string>) => {
        setNlStrings(data);
        setReady(true);
      })
      .catch(() => {
        setReady(true); // Fall back to English on error
      });
  }, [language, token]);

  const t: TranslateFunc = useCallback(
    (key: string, fallback?: string) => {
      if (language === "nl") {
        if (nlStrings[key]) return nlStrings[key];
        if (key === "ui.tell_me_about") return "Vertel me over";
      }
      return EN[key] ?? fallback ?? key;
    },
    [language, nlStrings],
  );

  const tn: TranslateNodeFunc = useCallback(
    (nodeId: string, originalTitle: string) => {
      if (language === "nl") {
        const key = `node.${nodeId}`;
        if (nlStrings[key]) return nlStrings[key];
      }
      return originalTitle;
    },
    [language, nlStrings],
  );

  return { t, tn, ready, language };
}
