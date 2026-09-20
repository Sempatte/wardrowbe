const createNextIntlPlugin = require('next-intl/plugin');

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone output is needed for our own Docker image (see Dockerfile, which copies
  // .next/standalone) but must be OFF for AWS Amplify Hosting's Next.js SSR compute, which
  // expects the default .next build output. WARDROWBE_STANDALONE_BUILD is set only in the
  // Dockerfile build stage, so Amplify (which doesn't set it) gets the default output.
  output: process.env.WARDROWBE_STANDALONE_BUILD === 'true' ? 'standalone' : undefined,
  experimental: {
    // Disable automatic static optimization for pages using client-side context
    missingSuspenseWithCSRBailout: false,
  },
  images: {
    unoptimized: true,
  },
  // Skip type checking and linting during build (already done in CI)
  typescript: {
    ignoreBuildErrors: true,
  },
  eslint: {
    ignoreDuringBuilds: true,
  },
  // /api/v1/* is proxied by app/api/v1/[...path]/route.ts rather than a rewrite here, because
  // rewrites() is serialized into routes-manifest.json at build time and so cannot honor a
  // runtime BACKEND_URL in the prebuilt image.
};

const withNextIntl = createNextIntlPlugin();
module.exports = withNextIntl(nextConfig);
