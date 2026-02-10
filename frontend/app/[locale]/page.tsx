'use client';

import Link from 'next/link';
import { useTranslations } from 'next-intl';
import { Link as IntlLink } from '@/i18n/routing';

export default function Home() {
  const t = useTranslations('nav');

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100">
      <div className="max-w-6xl mx-auto px-4 py-16">
        {/* Header */}
        <div className="text-center mb-16">
          <h1 className="text-5xl font-bold text-gray-900 mb-4">
            🚀 SOWKNOW4
          </h1>
          <p className="text-xl text-gray-600 mb-2">Multi-Generational Legacy Knowledge System</p>
          <p className="text-gray-500">Phase 3: Knowledge Graph + Graph-RAG + Multi-Agent Search</p>
        </div>

        {/* Feature Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-16">
          <IntlLink href="/knowledge-graph" className="group">
            <div className="bg-white rounded-xl shadow-sm hover:shadow-lg transition-shadow p-6 border border-gray-200 h-full">
              <div className="w-12 h-12 bg-purple-100 rounded-lg flex items-center justify-center mb-4 group-hover:bg-purple-200 transition-colors">
                <svg className="w-6 h-6 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                </svg>
              </div>
              <h3 className="text-lg font-semibold text-gray-900 mb-2">Knowledge Graph</h3>
              <p className="text-gray-600 text-sm">Explore entities, relationships, and timeline events from your documents</p>
            </div>
          </IntlLink>

          <IntlLink href="/collections" className="group">
            <div className="bg-white rounded-xl shadow-sm hover:shadow-lg transition-shadow p-6 border border-gray-200 h-full">
              <div className="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center mb-4 group-hover:bg-blue-200 transition-colors">
                <svg className="w-6 h-6 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                </svg>
              </div>
              <h3 className="text-lg font-semibold text-gray-900 mb-2">{t('collections')}</h3>
              <p className="text-gray-600 text-sm">Create dynamic collections with AI-powered natural language queries</p>
            </div>
          </IntlLink>

          <IntlLink href="/smart-folders" className="group">
            <div className="bg-white rounded-xl shadow-sm hover:shadow-lg transition-shadow p-6 border border-gray-200 h-full">
              <div className="w-12 h-12 bg-green-100 rounded-lg flex items-center justify-center mb-4 group-hover:bg-green-200 transition-colors">
                <svg className="w-6 h-6 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                </svg>
              </div>
              <h3 className="text-lg font-semibold text-gray-900 mb-2">{t('smart_folders')}</h3>
              <p className="text-gray-600 text-sm">AI-generated summaries and reports from your document collections</p>
            </div>
          </IntlLink>
        </div>

        {/* System Status */}
        <div className="bg-white rounded-xl shadow-sm p-8 border border-gray-200">
          <h2 className="text-2xl font-semibold text-gray-900 mb-6">📊 System Status</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <h3 className="text-sm font-medium text-gray-500 mb-3">Services</h3>
              <ul className="space-y-2">
                <li className="flex items-center text-sm">
                  <span className="w-2 h-2 bg-green-500 rounded-full mr-3"></span>
                  <span className="text-gray-700">Backend API:</span>
                  <a href="http://localhost:8000" target="_blank" rel="noopener noreferrer" className="ml-2 text-blue-600 hover:underline">
                    localhost:8000
                  </a>
                </li>
                <li className="flex items-center text-sm">
                  <span className="w-2 h-2 bg-green-500 rounded-full mr-3"></span>
                  <span className="text-gray-700">API Documentation:</span>
                  <a href="http://localhost:8000/api/docs" target="_blank" rel="noopener noreferrer" className="ml-2 text-blue-600 hover:underline">
                    /api/docs
                  </a>
                </li>
                <li className="flex items-center text-sm">
                  <span className="w-2 h-2 bg-green-500 rounded-full mr-3"></span>
                  <span className="text-gray-700">PostgreSQL:</span>
                  <span className="ml-2 text-gray-500">localhost:5432</span>
                </li>
                <li className="flex items-center text-sm">
                  <span className="w-2 h-2 bg-green-500 rounded-full mr-3"></span>
                  <span className="text-gray-700">Redis:</span>
                  <span className="ml-2 text-gray-500">localhost:6379</span>
                </li>
                <li className="flex items-center text-sm">
                  <span className="w-2 h-2 bg-green-500 rounded-full mr-3"></span>
                  <span className="text-gray-700">Frontend:</span>
                  <span className="ml-2 text-gray-500">localhost:3000</span>
                </li>
              </ul>
            </div>
            <div>
              <h3 className="text-sm font-medium text-gray-500 mb-3">Phase 3 Features</h3>
              <ul className="space-y-2">
                <li className="flex items-center text-sm">
                  <span className="w-2 h-2 bg-blue-500 rounded-full mr-3"></span>
                  <span className="text-gray-700">Knowledge Graph with Entity Extraction</span>
                </li>
                <li className="flex items-center text-sm">
                  <span className="w-2 h-2 bg-blue-500 rounded-full mr-3"></span>
                  <span className="text-gray-700">Graph-RAG Enhanced Search</span>
                </li>
                <li className="flex items-center text-sm">
                  <span className="w-2 h-2 bg-blue-500 rounded-full mr-3"></span>
                  <span className="text-gray-700">Multi-Agent Search Orchestration</span>
                </li>
                <li className="flex items-center text-sm">
                  <span className="w-2 h-2 bg-blue-500 rounded-full mr-3"></span>
                  <span className="text-gray-700">Smart Collections with AI</span>
                </li>
                <li className="flex items-center text-sm">
                  <span className="w-2 h-2 bg-blue-500 rounded-full mr-3"></span>
                  <span className="text-gray-700">Smart Folders with Content Generation</span>
                </li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
