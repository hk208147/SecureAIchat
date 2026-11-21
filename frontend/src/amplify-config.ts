import { Amplify } from 'aws-amplify';

const cognitoDomain = import.meta.env.VITE_COGNITO_DOMAIN as string | undefined ?? '';
if (cognitoDomain.startsWith('http://') || cognitoDomain.startsWith('https://')) {
  throw new Error(
    `VITE_COGNITO_DOMAIN must be a hostname only (no protocol). Got: ${cognitoDomain}`,
  );
}

Amplify.configure({
  Auth: {
    Cognito: {
      userPoolId: import.meta.env.VITE_USER_POOL_ID as string,
      userPoolClientId: import.meta.env.VITE_USER_POOL_CLIENT_ID as string,
      loginWith: {
        oauth: {
          domain: cognitoDomain,
          scopes: ['openid', 'email', 'profile', 'personal-chat-api/chat'],
          redirectSignIn: [`${window.location.origin}/callback`],
          redirectSignOut: [`${window.location.origin}/logout`],
          responseType: 'code',
        },
      },
    },
  },
});
