import type { Api } from "./api/client";
import { ConversationContainer } from "./features/ConversationContainer";
import { es } from "./i18n/es";

export function App({ api }: { api?: Api }) {
  return (
    <main className="mx-auto min-h-screen max-w-6xl bg-white p-4 text-slate-900 sm:p-6">
      <h1 className="mb-4 text-2xl font-semibold">{es.appTitle}</h1>
      <ConversationContainer api={api} />
    </main>
  );
}
