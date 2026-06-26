const ARENA_ADAPTERS = [
  {
    name: 'chatgpt',
    hosts: ['chat.openai.com', 'chatgpt.com'],
    selectors: ['article', '[data-message-author-role="assistant"]', 'main article'],
  },
  {
    name: 'claude',
    hosts: ['claude.ai'],
    selectors: ['article', '[data-test-render-count]', 'main article'],
  },
  {
    name: 'generic',
    hosts: [],
    selectors: ['article', 'main', 'section', 'pre', 'code'],
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
  adapter.selectors.forEach((selector) => {
    document.querySelectorAll(selector).forEach((node) => {
      if (!seen.has(node)) {
        seen.add(node);
        nodes.push(node);
      }
    });
  });
  return {adapter, nodes};
}
