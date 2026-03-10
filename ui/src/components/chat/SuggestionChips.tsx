/**
 * Context-aware follow-up suggestion chips for the chat interface.
 *
 * Shows different prompts based on:
 * - Whether a property is active (and its property_category)
 * - Which tools have been called already
 * - The conversation stage
 */

interface SuggestionChipsProps {
  hasProperty: boolean;
  toolsUsed: string[];
  onSelect: (prompt: string) => void;
  /** Granular property type (sfr, condo, land, etc.) for smarter suggestions. */
  propertyCategory?: string;
}

const INITIAL_PROMPTS = [
  'What\'s the Berkeley market like right now?',
  'Tell me about the Elmwood neighborhood',
  'Find properties with good development potential',
  'How are mortgage rates affecting prices?',
];

/** Property-type-aware initial prompts when a property is selected. */
function getPropertyPrompts(category?: string): string[] {
  const base = [
    'What\'s this property worth?',
    'Show comparable sales',
    'Should I sell or hold?',
  ];

  switch (category) {
    case 'sfr':
      return [
        ...base,
        'What can I build on this lot?',
        'What improvements add the most value?',
        'Run an investment analysis',
        'Estimate rental income',
        'Generate an investment prospectus',
      ];

    case 'condo':
    case 'coop':
    case 'townhouse':
      return [
        ...base,
        'What improvements add the most value?',
        'Estimate rental income',
        'How does this compare to similar units?',
      ];

    case 'duplex':
    case 'triplex':
    case 'fourplex':
      return [
        ...base,
        'Can I add an ADU?',
        'What improvements add the most value?',
        'Run an investment analysis',
        'Estimate rental income',
        'Generate an investment prospectus',
      ];

    case 'apartment':
      return [
        ...base,
        'What improvements add the most value?',
        'Estimate rental income for all units',
      ];

    case 'land':
      return [
        ...base,
        'What can I build here?',
        'What does the zoning allow?',
      ];

    case 'mixed_use':
      return [
        ...base,
        'What can I build on the residential portion?',
        'What improvements add the most value?',
        'Estimate rental income',
      ];

    default:
      return [
        ...base,
        'What can I build on this lot?',
        'What improvements add the most value?',
        'Run an investment analysis',
        'Generate an investment prospectus',
      ];
  }
}

/** Post-prediction follow-ups, filtered by property type. */
function getPostPredictionPrompts(category?: string): string[] {
  const base = [
    'What drives this price?',
    'Show comps nearby',
  ];

  switch (category) {
    case 'condo':
    case 'coop':
    case 'townhouse':
      return [...base, 'Sell vs hold analysis', 'Estimate rental income'];
    case 'land':
      return [...base, 'Sell vs hold analysis', 'What can I build here?'];
    case 'apartment':
      return [...base, 'Sell vs hold analysis', 'Estimate rental income'];
    default:
      return [...base, 'What can I build here?', 'Investment scenarios'];
  }
}

/** Post-development follow-ups, filtered by property type. */
function getPostDevelopmentPrompts(category?: string): string[] {
  switch (category) {
    case 'condo':
    case 'coop':
    case 'townhouse':
      // Development potential shouldn't have been run, but handle gracefully
      return [
        'Show comparable sales',
        'Estimate rental income',
      ];
    case 'land':
      return [
        'Show comparable land sales',
        'What are the construction costs?',
      ];
    default:
      return [
        'What\'s the ROI on adding an ADU?',
        'Compare investment scenarios',
        'Show comparable sales',
        'Estimate rental income with an ADU',
      ];
  }
}

const POST_SEARCH_PROMPTS = [
  'Which of these have the best development potential?',
  'Compare the top results by price per sqft',
  'Tell me more about the first property',
  'What are the average prices by neighborhood?',
];

const POST_INVESTMENT_PROMPTS = [
  'Generate an investment prospectus',
  'What are the risks?',
  'Show comparable sales',
  'What does the market look like?',
];

export function SuggestionChips({
  hasProperty,
  toolsUsed,
  onSelect,
  propertyCategory,
}: SuggestionChipsProps) {
  const prompts = getPrompts(hasProperty, toolsUsed, propertyCategory);

  if (prompts.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-1.5 pb-2">
      {prompts.map((prompt) => (
        <button
          key={prompt}
          onClick={() => onSelect(prompt)}
          className="text-xs px-3 py-1.5 rounded-full border border-gray-200 text-gray-600
                     hover:border-indigo-300 hover:text-indigo-700 hover:bg-indigo-50
                     transition-colors whitespace-nowrap"
        >
          {prompt}
        </button>
      ))}
    </div>
  );
}

function getPrompts(
  hasProperty: boolean,
  toolsUsed: string[],
  propertyCategory?: string,
): string[] {
  const tools = new Set(toolsUsed);

  // After property search, suggest exploration follow-ups
  if (tools.has('search_properties')) {
    return POST_SEARCH_PROMPTS.slice(0, 4);
  }

  // After investment scenario analysis, suggest prospectus and follow-ups
  if (tools.has('analyze_investment_scenarios')) {
    return POST_INVESTMENT_PROMPTS
      .filter((p) => !tools.has(promptToTool(p)))
      .slice(0, 4);
  }

  // After development potential, suggest related follow-ups
  if (tools.has('get_development_potential')) {
    return getPostDevelopmentPrompts(propertyCategory)
      .filter((p) => !tools.has(promptToTool(p)))
      .slice(0, 4);
  }

  // After prediction, suggest deeper analysis
  if (tools.has('get_price_prediction')) {
    return getPostPredictionPrompts(propertyCategory)
      .filter((p) => !tools.has(promptToTool(p)))
      .slice(0, 4);
  }

  // Property is active but no tools called yet
  if (hasProperty) {
    return getPropertyPrompts(propertyCategory).slice(0, 4);
  }

  // No property, no tools — initial prompts
  return INITIAL_PROMPTS;
}

/** Best-effort mapping from prompt text to tool name for deduplication. */
function promptToTool(prompt: string): string {
  const lower = prompt.toLowerCase();
  if (lower.includes('worth') || lower.includes('price') || lower.includes('value'))
    return 'get_price_prediction';
  if (lower.includes('build') || lower.includes('development') || lower.includes('zoning'))
    return 'get_development_potential';
  if (lower.includes('comp') || lower.includes('sales'))
    return 'get_comparable_sales';
  if (lower.includes('sell') || lower.includes('hold'))
    return 'estimate_sell_vs_hold';
  if (lower.includes('improvement') || lower.includes('roi') || lower.includes('renovation'))
    return 'get_improvement_simulation';
  if (lower.includes('prospectus'))
    return 'generate_investment_prospectus';
  if (lower.includes('investment') || lower.includes('scenario'))
    return 'analyze_investment_scenarios';
  if (lower.includes('rental') || lower.includes('rent'))
    return 'estimate_rental_income';
  if (lower.includes('market'))
    return 'get_market_summary';
  if (lower.includes('neighborhood'))
    return 'get_neighborhood_stats';
  return '';
}
