// Arena Chat Bridge — per-site adapter registry.
//
// Each entry pins the DOM shape of one chat UI so parser + composer +
// submit selection stay predictable. Kept as a plain array (no plugin
// factory) because MV3 content scripts cannot import ES modules and
// the registry rarely churns — a rare live-smoke session (v0.14.1)
// tightens a few selectors and adds three sites (Mistral, Kimi with
// its www.* subdomain, GitHub Copilot) that had been falling back to
// the generic adapter.
//
// v0.14.1 also broadened messageSelectors on adapters that reported
// zero candidate_nodes in scan-report diagnostics (DeepSeek, Qwen,
// Perplexity, Kimi): the previous selectors were too specific for
// how those SPAs render the assistant reply on first paint, so the
// scanner missed the fenced ```jsonl block entirely.
const ARENA_SITE_ADAPTERS = [
  {
    name: 'chatgpt',
    hosts: ['chat.openai.com', 'chatgpt.com'],
    messageSelectors: ['[data-message-author-role="assistant"]', 'article[data-testid^="conversation-turn-"]', 'main article'],
    composerSelectors: ['#prompt-textarea', 'textarea[placeholder*="Message"]', 'div#prompt-textarea[contenteditable="true"]'],
    submitSelectors: ['button[data-testid="send-button"]', 'button[data-testid*="send"]', 'form button[type="submit"]', 'button[type="submit"]', 'button[aria-label*="Send"]', 'button[aria-label*="Отправ"]', 'button svg[viewBox][aria-hidden="true"]'],
  },
  {
    name: 'claude',
    hosts: ['claude.ai'],
    messageSelectors: ['[data-test-render-count]'],
    composerSelectors: ['div.ProseMirror[contenteditable="true"]', 'div[contenteditable="true"]', 'textarea'],
    submitSelectors: ['button[aria-label="Send message"]', 'button[aria-label*="Send"]', 'fieldset button[type="submit"]', 'button[type="submit"]'],
  },
  {
    name: 'gemini',
    hosts: ['gemini.google.com', 'aistudio.google.com'],
    messageSelectors: ['message-content', 'model-response', 'pre', 'code', '[class*=\"code\"]', 'main article', 'main'],
    composerSelectors: ['rich-textarea div[contenteditable="true"]', 'textarea', '[contenteditable="true"]'],
    submitSelectors: ['button[aria-label*="Send"]', 'button[aria-label*="Send message"]', 'button.send-button', 'button[mattooltip*="Send"]', 'button[aria-label*="Run"]', 'button[type="submit"]'],
  },
  {
    name: 'perplexity',
    hosts: ['www.perplexity.ai', 'perplexity.ai'],
    // v0.14.1: perplexity reported zero parsed_blocks with the
    // previous selectors because their assistant reply is rendered
    // inside `main` div children rather than an <article>. Broaden
    // to include pre/code so fenced ```jsonl blocks are picked up
    // even on the first paint.
    messageSelectors: ['main [data-testid]', 'main article', 'main', 'pre', 'code', '[class*="prose"]', '[class*="markdown"]'],
    composerSelectors: ['textarea', '[contenteditable="true"]'],
    submitSelectors: ['button[aria-label*="Submit"]', 'button[aria-label*="Send"]', 'button[data-testid*="submit"]', 'button[type="submit"]'],
  },
  {
    name: 'grok',
    hosts: ['grok.com'],
    // v0.14.1: reflect real scan-report shape -- Grok uses
    // data-testid="chat-submit" and buttons live inside a <form>.
    messageSelectors: ['main [data-testid]', 'main article', 'main'],
    composerSelectors: ['div.ProseMirror[contenteditable="true"]', 'div[contenteditable="true"][role="textbox"]', 'textarea', '[contenteditable="true"]'],
    submitSelectors: ['button[data-testid="chat-submit"]', 'form button[type="submit"]', 'button[aria-label*="Send"]', 'button[aria-label*="Отправ"]', 'button[type="submit"]'],
  },
  {
    name: 'openrouter',
    hosts: ['openrouter.ai'],
    // v0.14.1: OpenRouter's real submit is data-testid="send-button"
    // + aria-label="Send message"; the previous selector matched
    // eventually but only via the very-generic Send fallback.
    messageSelectors: ['main [data-testid]', 'main article', 'main'],
    composerSelectors: ['textarea', '[contenteditable="true"]'],
    submitSelectors: ['button[data-testid="send-button"]', 'button[aria-label="Send message"]', 'button[aria-label*="Send"]', 'button[type="submit"]'],
  },
  {
    name: 'deepseek',
    hosts: ['chat.deepseek.com'],
    // v0.14.1: 0 candidate_nodes / 0 submit_scope_buttons in scans
    // -- their SPA renders the composer + reply lazily inside
    // deeper containers. Broaden messageSelectors to include
    // section / pre / code / prose-styled containers.
    messageSelectors: ['main [data-testid]', 'main article', 'main', 'section', 'pre', 'code', '[class*="markdown"]', '[class*="prose"]'],
    composerSelectors: ['textarea', '[contenteditable="true"]', 'div[role="textbox"]'],
    submitSelectors: ['div[role="button"][aria-label*="Send"]', 'div[role="button"][aria-label*="发送"]', 'button[aria-label*="Send"]', 'button[type="submit"]'],
  },
  {
    name: 'kimi',
    // v0.14.1: user hits kimi.com AND www.kimi.com -- host
    // permissions only listed the bare form, so the www.* subdomain
    // fell through to the generic adapter and lost site-specific
    // selectors. Both aliases now covered.
    hosts: ['kimi.com', 'www.kimi.com'],
    messageSelectors: ['main article', 'main [data-testid]', 'main', 'section', 'pre', 'code', '[class*="markdown"]'],
    composerSelectors: ['div[contenteditable="true"][role="textbox"]', 'div[contenteditable="true"]', 'textarea'],
    submitSelectors: ['button[aria-label*="Send"]', 'button[aria-label*="发送"]', 'div[role="button"][aria-label*="Send"]', 'button[type="submit"]'],
  },
  {
    name: 'qwen',
    hosts: ['chat.qwen.ai'],
    // v0.14.1: same broaden as deepseek -- the previous shape gave
    // 0 candidates on real Qwen chats.
    messageSelectors: ['main [data-testid]', 'main article', 'main', 'section', 'pre', 'code', '[class*="markdown"]', '[class*="prose"]'],
    composerSelectors: ['textarea', '[contenteditable="true"]', 'div[role="textbox"]'],
    submitSelectors: ['button[aria-label*="Send"]', 'button[aria-label*="发送"]', 'button[type="submit"]'],
  },
  {
    name: 't3chat',
    hosts: ['t3.chat'],
    messageSelectors: ['main article', 'main [data-testid]', 'main', 'pre', 'code'],
    composerSelectors: ['textarea', '[contenteditable="true"]'],
    submitSelectors: ['button[type="submit"]', 'button[aria-label*="Send"]', 'button[aria-label*="Отправ"]'],
  },
  {
    name: 'zai',
    hosts: ['chat.z.ai'],
    messageSelectors: ['main article', 'main [data-testid]', 'main', 'section', '[class*="message"]', '[class*="markdown"]', 'pre', 'code'],
    composerSelectors: ['textarea', '[contenteditable="true"]'],
    submitSelectors: ['button[type="submit"]', 'button[aria-label*="Send"]', 'button[aria-label*="Отправ"]'],
  },
  {
    // v0.14.1: Mistral was falling back to the generic adapter
    // because there was no entry here. Scan-report shows ProseMirror
    // composer + form-wrapped submit -- Claude-shaped, so its
    // selectors serve as the model.
    name: 'mistral',
    hosts: ['chat.mistral.ai'],
    messageSelectors: ['main article', 'main [data-testid]', 'main', 'section', 'pre', 'code', '[class*="prose"]', '[class*="markdown"]'],
    composerSelectors: ['div.ProseMirror[contenteditable="true"]', 'div[contenteditable="true"][role="textbox"]', 'div[contenteditable="true"]', 'textarea'],
    submitSelectors: ['form button[type="submit"]', 'button[type="submit"]', 'button[aria-label*="Send"]', 'button[aria-label*="Envoy"]'],
  },
  {
    // v0.14.1: GitHub Copilot chat -- host is github.com/copilot/*.
    // Composer is a plain <textarea aria-label="Ask anything ...">;
    // scan reported buttons-present-no-submit-match because the
    // submit control is icon-only with empty aria-label, so we add
    // a data-testid selector list first and fall through to the
    // "last visible button inside the composer form" heuristic that
    // the generic scan already tries.
    name: 'copilot',
    hosts: ['github.com'],
    // v0.14.2: copilot only exists at github.com/copilot/*.
    // Without the path guard the adapter matched every github.com
    // page and started injecting "detected function_call" toolbars
    // into ordinary repository READMEs whenever a README quoted
    // an MCP-style JSONL example (like srbhptl39/MCP-SuperAssistant
    // does on its own landing page). pathPrefix is a new adapter
    // field consumed by getArenaAdapter() in adapters.js.
    pathPrefix: '/copilot',
    messageSelectors: ['main [class*="prose"]', 'main [class*="markdown"]', 'main pre', 'main code', 'main article', 'main', 'article', 'pre', 'code'],
    composerSelectors: ['textarea[aria-label*="Ask anything"]', 'textarea[aria-label*="type @"]', 'textarea', '[contenteditable="true"]'],
    submitSelectors: ['button[data-testid="send-button"]', 'button[data-testid*="submit"]', 'button[aria-label*="Send"]', 'button[aria-label*="Submit"]', 'form button[type="submit"]', 'button[type="submit"]'],
  },
  {
    // v0.14.2: Arena.ai has multiple surfaces (chat / battle /
    // side-by-side / agent-mode / search / video / image /
    // code-fullstack). Baseline entry mirrors the ChatGPT shape --
    // enough to stop the site falling to `generic`. Battle-mode
    // multi-model handling is deferred to a follow-up; scan-report
    // showed the composer + submit are single-textarea + single-
    // submit-button on the /c/ URL so this baseline works for the
    // /c/ path today. Follow-up will add pathPrefix branches or
    // per-surface adapter variants.
    name: 'arenaai',
    // v0.14.18 (v4.50.8): pretty display name so toolbar reads
    // "Arena · Arena.ai" instead of the raw internal id ("arenaai").
    // Consumed by arenaAdapterLabel() in adapters.js.
    displayName: 'Arena.ai',
    hosts: ['arena.ai', 'www.arena.ai'],
    messageSelectors: ['main article', 'main [data-testid]', 'main', 'section', 'pre', 'code', '[class*="prose"]', '[class*="markdown"]'],
    composerSelectors: ['textarea', 'div[contenteditable="true"][role="textbox"]', '[contenteditable="true"]'],
    submitSelectors: ['button[aria-label="Send message"]', 'button[aria-label*="Send"]', 'form button[type="submit"]', 'button[type="submit"]'],
  },
  {
    // v0.14.2: DuckDuckGo AI chat -- scan-report showed a plain
    // textarea composer + form-wrapped submit with a locale-aware
    // aria-label ("Отправить" on the RU locale, "Send" on EN).
    // pathPrefix keeps the adapter from hijacking the rest of
    // duck.ai (search, news, etc.) which use different DOM.
    name: 'duckai',
    hosts: ['duck.ai', 'duckduckgo.com'],
    pathPrefix: '/chat',
    messageSelectors: ['main article', 'main [data-testid]', 'main', 'section', 'pre', 'code', '[class*="prose"]', '[class*="markdown"]'],
    composerSelectors: ['textarea', '[contenteditable="true"]'],
    submitSelectors: ['form button[type="submit"]', 'button[type="submit"]', 'button[aria-label*="Send"]', 'button[aria-label*="Отправ"]'],
  },
  {
    // v0.14.4: generic is now `passive` -- it never mounts toolbars
    // by itself. Was catching GitHub README code fences that quoted
    // MCP JSONL (bug #9 in the v0.14.3 scan-report). To enable a new
    // chat site, add an explicit entry above; generic exists only
    // to give scan-page diagnostics a shape when the operator opens
    // the popup on an unlisted site, so they can see the composer
    // is detectable and file a feature request.
    name: 'generic',
    passive: true,
    hosts: [],
    messageSelectors: ['article', 'main', 'section', 'pre', 'code'],
    composerSelectors: ['textarea', 'input[type="text"]', '[contenteditable="true"]'],
    submitSelectors: ['button[type="submit"]', 'button[aria-label*="Send"]'],
  },
];

