/**
 * Maps response block types to their corresponding chat card components.
 * Used by ChatPage to render rich structured data inline in conversations.
 *
 * Wrapped in an ErrorBoundary so a rendering crash in any block card
 * (e.g., missing fields, null dereferences) won't unmount the entire app.
 */
import { Component, type ReactNode } from 'react';
import type { ResponseBlock } from '../../types';
import { ChatPropertyCard } from './ChatPropertyCard';
import { ChatPredictionCard } from './ChatPredictionCard';
import { ChatCompsTable } from './ChatCompsTable';
import { ChatNeighborhoodStats } from './ChatNeighborhoodStats';
import { ChatDevelopmentCard } from './ChatDevelopmentCard';
import { ChatSellVsHoldCard } from './ChatSellVsHoldCard';
import { ChatMarketSummary } from './ChatMarketSummary';
import { ChatImprovementSim } from './ChatImprovementSim';
import { ChatInvestmentScenarios } from './ChatInvestmentScenarios';
import { ChatRentalIncome } from './ChatRentalIncome';
import { ChatSearchResults } from './ChatSearchResults';
import { ChatQueryResult } from './ChatQueryResult';
import { ChatInvestmentProspectus } from './ChatInvestmentProspectus';
import { ChatTrueCostCard } from './ChatTrueCostCard';
import { ChatRentVsBuyCard } from './ChatRentVsBuyCard';
import { ChatPmiModelCard } from './ChatPmiModelCard';
import { ChatRatePenaltyCard } from './ChatRatePenaltyCard';
import { ChatCompetitionCard } from './ChatCompetitionCard';
import { ChatDualPropertyCard } from './ChatDualPropertyCard';
import { ChatYieldRankingCard } from './ChatYieldRankingCard';
import { ChatAppreciationStressCard } from './ChatAppreciationStressCard';
import { ChatNeighborhoodLifestyleCard } from './ChatNeighborhoodLifestyleCard';
import { ChatAdjacentMarketCard } from './ChatAdjacentMarketCard';

// ---------------------------------------------------------------------------
// Error boundary — catches render crashes in any block card
// ---------------------------------------------------------------------------

interface EBProps {
  children: ReactNode;
  blockType: string;
}
interface EBState {
  error: Error | null;
}

class BlockErrorBoundary extends Component<EBProps, EBState> {
  state: EBState = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error(`BlockRenderer crash in "${this.props.blockType}":`, error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 my-2 text-xs text-red-700">
          <p className="font-medium">Failed to render {this.props.blockType} card</p>
          <p className="text-red-500 mt-1 truncate">{this.state.error.message}</p>
        </div>
      );
    }
    return this.props.children;
  }
}

// ---------------------------------------------------------------------------
// Block renderer
// ---------------------------------------------------------------------------

interface BlockRendererProps {
  block: ResponseBlock;
  /** Callback when a property address is clicked in a block card. */
  onAddressClick?: (address: string) => void;
}

export function BlockRenderer({ block, onAddressClick }: BlockRendererProps) {
  let content: ReactNode;

  switch (block.type) {
    case 'property_detail':
      content = <ChatPropertyCard data={block.data} onAddressClick={onAddressClick} />;
      break;
    case 'prediction_card':
      content = <ChatPredictionCard data={block.data} />;
      break;
    case 'comps_table':
      content = <ChatCompsTable data={block.data} onAddressClick={onAddressClick} />;
      break;
    case 'neighborhood_stats':
      content = <ChatNeighborhoodStats data={block.data} />;
      break;
    case 'development_potential':
      content = <ChatDevelopmentCard data={block.data} />;
      break;
    case 'sell_vs_hold':
      content = <ChatSellVsHoldCard data={block.data} />;
      break;
    case 'market_summary':
      content = <ChatMarketSummary data={block.data} />;
      break;
    case 'improvement_sim':
      content = <ChatImprovementSim data={block.data} />;
      break;
    case 'investment_scenarios':
      content = <ChatInvestmentScenarios data={block.data} />;
      break;
    case 'rental_income':
      content = <ChatRentalIncome data={block.data} />;
      break;
    case 'property_search_results':
      content = <ChatSearchResults data={block.data} onAddressClick={onAddressClick} />;
      break;
    case 'query_result':
      content = <ChatQueryResult data={block.data} />;
      break;
    case 'investment_prospectus':
      content = <ChatInvestmentProspectus data={block.data} />;
      break;
    case 'true_cost_card':
      content = <ChatTrueCostCard data={block.data} />;
      break;
    case 'rent_vs_buy_card':
      content = <ChatRentVsBuyCard data={block.data} />;
      break;
    case 'pmi_model_card':
      content = <ChatPmiModelCard data={block.data} />;
      break;
    case 'rate_penalty_card':
      content = <ChatRatePenaltyCard data={block.data} />;
      break;
    case 'competition_card':
      content = <ChatCompetitionCard data={block.data} />;
      break;
    case 'dual_property_card':
      content = <ChatDualPropertyCard data={block.data} />;
      break;
    case 'yield_ranking_card':
      content = <ChatYieldRankingCard data={block.data} onAddressClick={onAddressClick} />;
      break;
    case 'appreciation_stress_card':
      content = <ChatAppreciationStressCard data={block.data} />;
      break;
    case 'neighborhood_lifestyle_card':
      content = <ChatNeighborhoodLifestyleCard data={block.data} />;
      break;
    case 'adjacent_market_card':
      content = <ChatAdjacentMarketCard data={block.data} />;
      break;
    default: {
      const _exhaustive: never = block;
      void _exhaustive;
      return null;
    }
  }

  return (
    <BlockErrorBoundary blockType={block.type}>
      {content}
    </BlockErrorBoundary>
  );
}
