import { useState, useEffect, useRef } from 'react';
import {
  Loader2,
  Building2,
  Home,
  Scissors,
  Zap,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ExternalLink,
} from 'lucide-react';
import { toast } from 'sonner';
import { AddressSearch } from '../components/AddressSearch';
import { ImprovementSimCard } from '../components/ImprovementSimCard';
import { RentalIncomeCard } from '../components/RentalIncomeCard';
import { InvestmentScenarioCard } from '../components/InvestmentScenarioCard';
import { usePropertyContext } from '../context/PropertyContext';
import * as api from '../lib/tauri';
import { formatNumber } from '../lib/utils';
import type { DevelopmentPotentialResponse } from '../types';

// ---------------------------------------------------------------------------
// Lookup helpers for contextual notes
// ---------------------------------------------------------------------------

const GENERAL_PLAN_LABELS: Record<string, string> = {
  LDR: 'Low Density Residential — single-family homes, up to ~1 unit per lot',
  MDR: 'Medium Density Residential — duplexes to small apartments',
  HDR: 'High Density Residential — multi-story apartments and condos',
  NC: 'Neighborhood Commercial — small-scale retail and services',
  BC: 'Boulevard Commercial — auto-oriented strip commercial',
  DT: 'Downtown — mixed-use urban core',
  MU: 'Mixed Use — residential and commercial combined',
  RMU: 'Residential Mixed Use — primarily residential with ground-floor retail',
  I: 'Institutional — schools, churches, government facilities',
  OS: 'Open Space — parks, hillsides, and recreation areas',
  M: 'Manufacturing — light industrial and warehousing',
  W: 'Waterfront — marina and waterfront-related uses',
  MRD: 'Manufacturing Research & Development',
};

function RefLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-0.5 text-blue-600 hover:text-blue-800 hover:underline"
    >
      {children}
      <ExternalLink size={10} className="shrink-0" />
    </a>
  );
}

export function PotentialPage() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<DevelopmentPotentialResponse | null>(null);
  const [selectedAddress, setSelectedAddress] = useState('');
  const [selectedCoords, setSelectedCoords] = useState<{ lat: number; lng: number } | null>(null);
  const { lastProperty } = usePropertyContext();
  const autoLoaded = useRef(false);

  // Auto-load from Predict page context when navigating via "View Details"
  useEffect(() => {
    if (lastProperty && !autoLoaded.current && !result && !loading) {
      autoLoaded.current = true;
      handleAddressSelect(
        lastProperty.latitude,
        lastProperty.longitude,
        lastProperty.address,
      );
    }
  }, [lastProperty]);

  async function handleAddressSelect(lat: number, lng: number, address: string) {
    setLoading(true);
    setSelectedAddress(address);
    setSelectedCoords({ lat, lng });
    setResult(null);
    try {
      const data = await api.getPropertyPotential({
        latitude: lat,
        longitude: lng,
        address,
      });
      setResult(data);
    } catch (err) {
      toast.error('Failed to compute development potential');
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Development Potential</h2>
        <p className="text-sm text-gray-500 mt-1">
          Assess ADU feasibility, Middle Housing potential, SB 9 lot splitting, and improvement ROI.
        </p>
      </div>

      {/* Address Search */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Search for a Berkeley address
        </label>
        <AddressSearch onSelect={handleAddressSelect} disabled={loading} />
        {selectedAddress && !loading && (
          <p className="text-xs text-gray-500 mt-2">Showing results for: {selectedAddress}</p>
        )}
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-6 h-6 animate-spin text-blue-500 mr-2" />
          <span className="text-gray-500">Analyzing development potential...</span>
        </div>
      )}

      {/* Results */}
      {result && !loading && (
        <div className="space-y-4">
          {/* Zoning Summary */}
          <ZoningSummaryCard result={result} />

          {/* Unit Potential */}
          {result.units && <UnitPotentialCard result={result} />}

          {/* ADU Feasibility */}
          {result.adu && <ADUCard result={result} />}

          {/* SB 9 Lot Split */}
          {result.sb9 && <SB9Card result={result} />}

          {/* BESO Status */}
          <BESOCard result={result} />

          {/* Improvement Simulation */}
          {selectedCoords && (
            <ImprovementSimCard
              latitude={selectedCoords.lat}
              longitude={selectedCoords.lng}
              address={selectedAddress}
            />
          )}

          {/* Rental Income Analysis */}
          {selectedCoords && (
            <RentalIncomeCard
              latitude={selectedCoords.lat}
              longitude={selectedCoords.lng}
              address={selectedAddress}
            />
          )}

          {/* Investment Scenario Comparison */}
          {selectedCoords && (
            <InvestmentScenarioCard
              latitude={selectedCoords.lat}
              longitude={selectedCoords.lng}
              address={selectedAddress}
            />
          )}

        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatusBadge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium ${
        ok
          ? 'bg-green-50 text-green-700 border border-green-200'
          : 'bg-red-50 text-red-700 border border-red-200'
      }`}
    >
      {ok ? <CheckCircle2 size={12} /> : <XCircle size={12} />}
      {label}
    </span>
  );
}

function ZoningSummaryCard({ result }: { result: DevelopmentPotentialResponse }) {
  const z = result.zoning;
  const r = result.zone_rule;

  if (!z) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <div className="flex items-center gap-2 mb-3">
          <Building2 size={18} className="text-gray-400" />
          <h3 className="font-semibold text-gray-900">Zoning</h3>
        </div>
        <p className="text-sm text-gray-500">
          This location is outside Berkeley zoning boundaries.
        </p>
      </div>
    );
  }

  const gpLabel = z.general_plan ? GENERAL_PLAN_LABELS[z.general_plan] : null;
  const coveragePct = r ? Math.round(r.max_lot_coverage_pct * 100) : null;

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6">
      <div className="flex items-center gap-2 mb-4">
        <Building2 size={18} className="text-blue-500" />
        <h3 className="font-semibold text-gray-900">Zoning Summary</h3>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wide">Zone</p>
          <p className="text-lg font-bold text-blue-600 mt-0.5">{z.zone_class}</p>
          <p className="text-xs text-gray-400 mt-0.5">
            Berkeley Municipal Code{' '}
            <RefLink href="https://berkeley.municipal.codes/BMC/23">Title 23</RefLink>
          </p>
        </div>
        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wide">Description</p>
          <p className="text-sm font-medium text-gray-900 mt-0.5">{z.zone_desc ?? '—'}</p>
          <p className="text-xs text-gray-400 mt-0.5">
            Determines allowed uses and building types in this district
          </p>
        </div>
        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wide">General Plan</p>
          <p className="text-sm font-medium text-gray-900 mt-0.5">{z.general_plan ?? '—'}</p>
          <p className="text-xs text-gray-400 mt-0.5">
            {gpLabel ?? 'City land use designation from the General Plan'}
          </p>
        </div>
        {r && (
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wide">Max Coverage</p>
            <p className="text-sm font-medium text-gray-900 mt-0.5">{coveragePct}%</p>
            <p className="text-xs text-gray-400 mt-0.5">
              Max {coveragePct}% of lot area can be covered by structures
            </p>
          </div>
        )}
      </div>
      {r && (
        <div className="flex flex-wrap items-center gap-2 mt-4">
          {r.is_hillside && (
            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-50 text-amber-700 border border-amber-200">
              <AlertTriangle size={12} />
              Hillside Overlay
            </span>
          )}
          <StatusBadge ok={r.residential} label={r.residential ? 'Residential' : 'Non-Residential'} />
          {r.is_hillside && (
            <span className="text-xs text-gray-400 ml-1">
              Stricter setbacks, height limits, and fire safety requirements apply
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function UnitPotentialCard({ result }: { result: DevelopmentPotentialResponse }) {
  const u = result.units!;

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6">
      <div className="flex items-center gap-2 mb-4">
        <Home size={18} className="text-purple-500" />
        <h3 className="font-semibold text-gray-900">Unit Potential</h3>
      </div>
      <div className="grid grid-cols-3 gap-4 mb-4">
        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wide">Base Max Units</p>
          <p className="text-2xl font-bold text-gray-900 mt-0.5">{u.base_max_units}</p>
          <p className="text-xs text-gray-400 mt-0.5">
            Allowed under current zoning without any bonuses
          </p>
        </div>
        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wide">Middle Housing</p>
          <p className="text-2xl font-bold text-gray-900 mt-0.5">
            {u.middle_housing_max_units ?? '—'}
          </p>
          <p className="text-xs text-gray-400 mt-0.5">
            {u.middle_housing_max_units != null
              ? 'Additional units allowed under MH Ordinance'
              : 'Not applicable to this zone or lot'}
          </p>
        </div>
        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wide">Effective Max</p>
          <p className="text-2xl font-bold text-blue-600 mt-0.5">{u.effective_max_units}</p>
          <p className="text-xs text-gray-400 mt-0.5">
            Best of base zoning or Middle Housing allowance
          </p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge
          ok={u.middle_housing_eligible}
          label={u.middle_housing_eligible ? 'MH Eligible' : 'MH Not Eligible'}
        />
      </div>
      {u.middle_housing_eligible ? (
        <p className="text-xs text-gray-500 mt-2">
          Berkeley{' '}
          <RefLink href="https://berkeleyca.gov/construction-development/land-use-development/middle-housing">
            Middle Housing Ordinance
          </RefLink>{' '}
          (Nov 2025) allows up to {u.middle_housing_max_units} units by right on lots 5,000+ sqft
          with 60% lot coverage. No special permit required.
        </p>
      ) : (
        <p className="text-xs text-gray-500 mt-2">
          Not eligible for Middle Housing — requires a non-hillside residential zone (R-1, R-2, R-2A, or MU-R)
          with a lot of 5,000+ sqft.{' '}
          <RefLink href="https://berkeleyca.gov/construction-development/land-use-development/middle-housing">
            Learn more
          </RefLink>
        </p>
      )}
    </div>
  );
}

function ADUCard({ result }: { result: DevelopmentPotentialResponse }) {
  const a = result.adu!;

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6">
      <div className="flex items-center gap-2 mb-4">
        <Home size={18} className="text-green-500" />
        <h3 className="font-semibold text-gray-900">ADU Feasibility</h3>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-4">
        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wide">Eligible</p>
          <div className="mt-1">
            <StatusBadge ok={a.eligible} label={a.eligible ? 'Yes' : 'No'} />
          </div>
          <p className="text-xs text-gray-400 mt-1">
            {a.eligible
              ? 'This zone allows adding an ADU'
              : 'ADU not feasible at this location'}
          </p>
        </div>
        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wide">Max ADU Size</p>
          <p className="text-lg font-bold text-gray-900 mt-0.5">
            {formatNumber(a.max_adu_sqft)} sqft
          </p>
          <p className="text-xs text-gray-400 mt-0.5">
            Detached ADU size limit per CA state law + Berkeley rules
          </p>
        </div>
        {a.remaining_lot_coverage_sqft != null && (
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wide">Remaining Coverage</p>
            <p className="text-lg font-bold text-gray-900 mt-0.5">
              {formatNumber(a.remaining_lot_coverage_sqft)} sqft
            </p>
            <p className="text-xs text-gray-400 mt-0.5">
              Available buildable area after existing structures
            </p>
          </div>
        )}
      </div>
      {a.notes && <p className="text-xs text-gray-500">{a.notes}</p>}
      <p className="text-xs text-gray-400 mt-2">
        ADU = Accessory Dwelling Unit (e.g. backyard cottage, in-law unit). Berkeley allows 1 ADU per lot with
        4ft side/rear setbacks.{' '}
        <RefLink href="https://berkeleyca.gov/construction-development/land-use-development/accessory-dwelling-units-adus">
          Berkeley ADU guide
        </RefLink>
      </p>
    </div>
  );
}

function SB9Card({ result }: { result: DevelopmentPotentialResponse }) {
  const s = result.sb9!;

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6">
      <div className="flex items-center gap-2 mb-4">
        <Scissors size={18} className="text-orange-500" />
        <h3 className="font-semibold text-gray-900">SB 9 Lot Split</h3>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-4">
        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wide">Eligible Zone</p>
          <div className="mt-1">
            <StatusBadge ok={s.eligible} label={s.eligible ? 'Yes' : 'No'} />
          </div>
          <p className="text-xs text-gray-400 mt-1">
            {s.eligible
              ? 'Single-family zone qualifies for SB 9'
              : 'Only R-1 and R-1H zones qualify'}
          </p>
        </div>
        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wide">Can Split</p>
          <div className="mt-1">
            <StatusBadge ok={s.can_split} label={s.can_split ? 'Yes' : 'No'} />
          </div>
          <p className="text-xs text-gray-400 mt-1">
            {s.can_split
              ? 'Lot is large enough to split (min 2,400 sqft)'
              : 'Requires min 2,400 sqft lot, each resulting lot ≥ 1,200 sqft'}
          </p>
        </div>
        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wide">Max Total Units</p>
          <p className="text-lg font-bold text-gray-900 mt-0.5">{s.max_total_units}</p>
          <p className="text-xs text-gray-400 mt-0.5">
            Up to 2 units per resulting lot after split
          </p>
        </div>
      </div>
      {s.resulting_lot_sizes && (
        <p className="text-xs text-gray-500 mb-1">
          Resulting lots: {s.resulting_lot_sizes.map((sz) => formatNumber(sz) + ' sqft').join(' + ')}
        </p>
      )}
      {s.notes && <p className="text-xs text-gray-500">{s.notes}</p>}
      <p className="text-xs text-gray-400 mt-2">
        SB 9 (CA Senate Bill 9) allows splitting single-family lots and building duplexes, ministerially
        approved without discretionary review.{' '}
        <RefLink href="https://www.hcd.ca.gov/planning-and-community-development/sb-9">
          CA HCD SB 9 guide
        </RefLink>
      </p>
    </div>
  );
}

function BESOCard({ result }: { result: DevelopmentPotentialResponse }) {
  const records = result.beso;

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6">
      <div className="flex items-center gap-2 mb-4">
        <Zap size={18} className="text-yellow-500" />
        <h3 className="font-semibold text-gray-900">BESO Energy Status</h3>
      </div>
      {records.length === 0 ? (
        <div>
          <p className="text-sm text-gray-500">
            No BESO records found for this address.
          </p>
          <p className="text-xs text-gray-400 mt-1">
            BESO (Building Energy Saving Ordinance) requires commercial buildings &gt;15,000 sqft to benchmark
            energy use annually and is required at time of sale since Jan 2026. Most residential properties
            are exempt.{' '}
            <RefLink href="https://berkeleyca.gov/construction-development/green-building/building-energy-saving-ordinance-beso">
              BESO details
            </RefLink>
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {records.map((r, i) => (
            <div key={i} className="border border-gray-100 rounded-lg p-4">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div>
                  <p className="text-xs text-gray-500">Energy Star Score</p>
                  <p className="text-lg font-bold text-gray-900">
                    {r.energy_star_score ?? '—'}
                    {r.energy_star_score != null && (
                      <span className="text-xs text-gray-400 ml-1">/ 100</span>
                    )}
                  </p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    1–100 scale; 50 = median, 75+ = high performer
                  </p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Site EUI</p>
                  <p className="text-lg font-bold text-gray-900">
                    {r.site_eui != null ? r.site_eui.toFixed(1) : '—'}
                    {r.site_eui != null && (
                      <span className="text-xs text-gray-400 ml-1">kBTU/ft²</span>
                    )}
                  </p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Energy Use Intensity — lower is more efficient
                  </p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Status</p>
                  <p className="text-sm font-medium text-gray-900 mt-0.5">
                    {r.benchmark_status ?? '—'}
                  </p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Compliance status with BESO benchmarking
                  </p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Year</p>
                  <p className="text-sm font-medium text-gray-900 mt-0.5">
                    {r.reporting_year ?? '—'}
                  </p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Most recent reporting period
                  </p>
                </div>
              </div>
            </div>
          ))}
          <p className="text-xs text-gray-400">
            Data from{' '}
            <RefLink href="https://data.cityofberkeley.info/resource/8k7b-6awf">
              Berkeley Open Data
            </RefLink>
            . Low Energy Star scores or high EUI may affect resale value or trigger upgrade requirements.
          </p>
        </div>
      )}
    </div>
  );
}

