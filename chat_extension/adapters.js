const ARENA_ADAPTERS = [
  {
    name: 'chatgpt',
    hosts: ['chat.openai.com', 'chatgpt.com'],
    messageSelectors: [
      '[data-message-author-role="assistant"]',
      'article[data-testid^="conversation-turn-"]',
      'main article',
    ],
    composerSelectors: ['#prompt-textarea', 'textarea[placeholder*="Message"]', 'div#prompt-textarea[contenteditable="true"]'],
  },
  {
    name: 'claude',
    hosts: ['claude.ai'],
    messageSelectors: ['article', '[data-test-render-count]', 'main article'],
    composerSelectors: ['div[contenteditable="true"]', 'textarea'],
  },
  {
    name: 'generic',
    hosts: [],
    messageSelectors: ['article', 'main', 'section', 'pre', 'code'],
    composerSelectors: ['textarea', 'input[type="text"]', '[contenteditable="true"]'],
  },
];

function arenaHost() {
  return (location.hostname || '').toLowerCase();
}

function getArenaAdapter() {
  const host = arenaHost();
  return ARENA_ADAPTERS.find((adapter) => adapter.hosts.includes(host)) || ARENA_ADAPTERS[ARENA_ADAPTERS.length - 1];
}

function arenaCandidateNodes() {
  const adapter = getArenaAdapter();
  const seen = new Set();
  const nodes = [];
  adapter.messageSelectors.forEach((selector) => {
    document.querySelectorAll(selector).forEach((node) => {
      if (!seen.has(node)) {
        seen.add(node);
        nodes.push(node);
      }
    });
  });
  return {adapter, nodes};
}

function arenaFindComposer(adapter = getArenaAdapter()) {
  for (const selector of adapter.composerSelectors || []) {
    const node = document.querySelector(selector);
    if (node) return node;
  }
  return null;
}

function arenaInsertResult(text, adapter = getArenaAdapter()) {
  const target = arenaFindComposer(adapter);
  if (!target) return false;
  target.focus();
  if (target.tagName === 'TEXTAREA' || (target.tagName === 'INPUT' && target.type === 'text')) {
    const value = target.value || '';
    const start = target.selectionStart ?? value.length;
    const end = target.selectionEnd ?? value.length;
    target.value = `${value.slice(0, start)}${text}${value.slice(end)}`;
    target.dispatchEvent(new Event('input', {bubbles: true}));
    target.dispatchEvent(new Event('change', {bubbles: true}));
    return true;
  }
  if (target.isContentEditable) {
    const current = target.textContent || '';
    target.textContent = `${current}${text}`;
    target.dispatchEvent(new InputEvent('input', {bubbles: true, data: text, inputType: 'insertText'}));
    return true;
  }
  return false;
}
