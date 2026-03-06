/**
 * Context-aware follow-up suggestion chips for the chat interface.
 *
 * Shows different prompts based on:
 * - Whether a property is active
 * - Which tools have been called already
 * - The conversation stage
 */

interface SuggestionChipsProps {
  hasProperty: boolean;
  toolsUsed: string[];
  onSelect: (prompt: string) => void;
}

const INITIAL_PROMPTS = [
  'What\'s the Berkeley market like right now?',
  'Tell me about the Elmwood neighborhood',
  'Find properties with good development potential',
  'How are mortgage rates affecting prices?',
];

const PROPERTY_PROMPTS = [
  'What\'s this property worth?',
  'What can I build on this lot?',
  'Show comparable sales',
  'Should I sell or hold?',
  'What improvements add the most value?',
  'Run an investment analysis',
  'Estimate rental income',
];

const POST_PREDICTION_PROMPTS = [
  'What drives this price?',
  'Show comps nearby',
  'What can I build here?',
  'Sell vs hold analysis',
  'Investment scenarios',
];

const POST_DEVELOPMENT_PROMPTS = [
  'What\'s the ROI on adding an ADU?',
  'Compare investment scenarios',
  'Show comparable sales',
  'Estimate rental income with an ADU',
];

export function SuggestionChips({ hasProperty, toolsUsed, onSelect }: SuggestionChipsProps) {
  const prompts = getPrompts(hasProperty, toolsUsed);

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

function getPrompts(hasProperty: boolean, toolsUsed: string[]): string[] {
  const tools = new Set(toolsUsed);

  // After development potential, suggest related follow-ups
  if (tools.has('get_development_potential')) {
    return POST_DEVELOPMENT_PROMPTS.filter(
      (p) => !tools.has(promptToTool(p)),
    ).slice(0, 4);
  }

  // After prediction, suggest deeper analysis
  if (tools.has('get_price_prediction')) {
    return POST_PREDICTION_PROMPTS.filter(
      (p) => !tools.has(promptToTool(p)),
    ).slice(0, 4);
  }

  // Property is active but no tools called yet
  if (hasProperty) {
    return PROPERTY_PROMPTS.slice(0, 4);
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
