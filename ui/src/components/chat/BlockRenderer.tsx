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

export function BlockRenderer({ block }: { block: ResponseBlock }) {
  switch (block.type) {
    case 'property_detail':
      return <ChatPropertyCard data={block.data} />;
    case 'prediction_card':
      return <ChatPredictionCard data={block.data} />;
    case 'comps_table':
      return <ChatCompsTable data={block.data} />;
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
    default:
      return null;
  }
}
