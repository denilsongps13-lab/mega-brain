import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'br.com.megacerebro.app',
  appName: 'Mega Cérebro',
  webDir: '../web/out',
  server: {
    hostname: 'localhost',
    androidScheme: 'https'
  }
};

export default config;
