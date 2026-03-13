/**
 * Shared password validation rules and strength calculation.
 *
 * Single source of truth — used by AuthForm, AccountSettings, and any
 * future component that needs password-strength feedback.
 */

export interface PasswordRule {
  label: string;
  test: (pw: string) => boolean;
}

/** Must match the backend rules in `src/homebuyer/api.py`. */
export const PASSWORD_RULES: PasswordRule[] = [
  { label: 'At least 8 characters', test: (pw) => pw.length >= 8 },
  { label: 'One uppercase letter', test: (pw) => /[A-Z]/.test(pw) },
  { label: 'One lowercase letter', test: (pw) => /[a-z]/.test(pw) },
  { label: 'One digit', test: (pw) => /\d/.test(pw) },
  { label: 'One special character', test: (pw) => /[!@#$%^&*()_+\-=[\]{};':"\\|,.<>/?`~]/.test(pw) },
];

export interface PasswordStrength {
  score: number;
  label: string;
  color: string;
}

export function getPasswordStrength(pw: string): PasswordStrength {
  const passed = PASSWORD_RULES.filter((r) => r.test(pw)).length;
  if (passed <= 2) return { score: passed, label: 'Weak', color: 'bg-red-500' };
  if (passed <= 3) return { score: passed, label: 'Fair', color: 'bg-yellow-500' };
  if (passed <= 4) return { score: passed, label: 'Good', color: 'bg-blue-500' };
  return { score: passed, label: 'Strong', color: 'bg-green-500' };
}
