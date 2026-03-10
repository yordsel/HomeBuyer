/**
 * Maps response block types to their corresponding chat card components.
 * Used by ChatPage to render rich structured data inline in conversations.
 */
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

interface BlockRendererProps {
  block: ResponseBlock;
  /** Callback when a property address is clicked in a block card. */
  onAddressClick?: (address: string) => void;
}

export function BlockRenderer({ block, onAddressClick }: BlockRendererProps) {
  switch (block.type) {
    case 'property_detail':
      return <ChatPropertyCard data={block.data} onAddressClick={onAddressClick} />;
    case 'prediction_card':
      return <ChatPredictionCard data={block.data} />;
    case 'comps_table':
      return <ChatCompsTable data={block.data} onAddressClick={onAddressClick} />;
    case 'neighborhood_stats':
      return <ChatNeighborhoodStats data={block.data} />;
    case 'development_potential':
      return <ChatDevelopmentCard data={block.data} />;
    case 'sell_vs_hold':
      return <ChatSellVsHoldCard data={block.data} />;
    case 'market_summary':
      return <ChatMarketSummary data={block.data} />;
    case 'improvement_sim':
      return <ChatImprovementSim data={block.data} />;
    case 'investment_scenarios':
      return <ChatInvestmentScenarios data={block.data} />;
    case 'rental_income':
      return <ChatRentalIncome data={block.data} />;
    case 'property_search_results':
      return <ChatSearchResults data={block.data} onAddressClick={onAddressClick} />;
    case 'query_result':
      return <ChatQueryResult data={block.data} />;
    case 'investment_prospectus':
      return <ChatInvestmentProspectus data={block.data} />;
    default:
      return null;
  }
}
