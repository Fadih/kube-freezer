import { api } from './api';

/**
 * Test if an API key is valid by making an authenticated request
 */
export async function validateApiKey(apiKey: string): Promise<boolean> {
  try {
    // Trim whitespace from API key
    const trimmedKey = apiKey.trim();
    
    // Set the token temporarily
    api.setToken(trimmedKey);
    
    // Try to fetch exemptions (this endpoint requires authentication)
    // This will validate the API key properly
    await api.getExemptions();
    
    // If successful, token is valid
    return true;
  } catch (error) {
    // If it fails, token is invalid
    return false;
  }
}

/**
 * Login with API key
 */
export async function login(apiKey: string): Promise<boolean> {
  // Trim whitespace from API key
  const trimmedKey = apiKey.trim();
  const isValid = await validateApiKey(trimmedKey);
  if (isValid) {
    // Token is already set in validateApiKey, but ensure it's the trimmed version
    api.setToken(trimmedKey);
    return true;
  }
  return false;
}

/**
 * Logout
 */
export function logout() {
  api.clearToken();
}

/**
 * Check if user is authenticated
 */
export function isAuthenticated(): boolean {
  return api.isAuthenticated();
}

