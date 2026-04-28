const LEGACY_TOKEN_KEY = "krip3accesss1secret2token0";

export function removeToken(): void {
  localStorage.removeItem(LEGACY_TOKEN_KEY);
}
