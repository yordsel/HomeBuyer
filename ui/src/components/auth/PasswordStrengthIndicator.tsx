import { useMemo } from 'react';
import { Check, X } from 'lucide-react';
import { PASSWORD_RULES, getPasswordStrength } from '../../lib/password';

/**
 * Renders a strength bar + rule checklist for a password field.
 *
 * Shown beneath the password input during registration and password-reset
 * flows. Theme-neutral — uses standard green/red for pass/fail, and the
 * strength-bar color comes from `getPasswordStrength`.
 */
export function PasswordStrengthIndicator({ password }: { password: string }) {
  const strength = useMemo(() => getPasswordStrength(password), [password]);

  return (
    <div className="mt-2 space-y-2">
      {/* Strength bar */}
      <div className="flex items-center gap-2">
        <div className="flex-1 h-1.5 bg-gray-200 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${strength.color}`}
            style={{ width: `${(strength.score / PASSWORD_RULES.length) * 100}%` }}
          />
        </div>
        <span className="text-xs font-medium text-gray-500">{strength.label}</span>
      </div>

      {/* Rule checklist */}
      <ul className="space-y-0.5">
        {PASSWORD_RULES.map((rule) => {
          const passed = rule.test(password);
          return (
            <li
              key={rule.label}
              className={`flex items-center gap-1.5 text-xs ${passed ? 'text-green-600' : 'text-gray-400'}`}
            >
              {passed ? <Check size={12} /> : <X size={12} />}
              {rule.label}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
