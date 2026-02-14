import React, { useState } from 'react';
import { 
  View, 
  Text, 
  TextInput, 
  StyleSheet, 
  TouchableOpacity, 
  Alert,
  ActivityIndicator
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import api from '../../utils/api';
import { useAuth } from '../../contexts/AuthContext';

export default function VerifyOTP() {
  const router = useRouter();
  const params = useLocalSearchParams();
  const { login } = useAuth();
  const [otp, setOtp] = useState('');
  const [loading, setLoading] = useState(false);

  const handleVerifyAndRegister = async () => {
    if (!otp || otp.length !== 6) {
      Alert.alert('Error', 'Please enter a valid 6-digit OTP');
      return;
    }

    setLoading(true);
    try {
      // First verify OTP
      await api.post('/api/auth/verify-otp', {
        mobile: params.mobile,
        otp,
      });

      // Then register user
      const registerResponse = await api.post('/api/auth/register', {
        username: params.username,
        mobile: params.mobile,
        email: params.email,
        age: parseInt(params.age as string),
        password: params.password,
      });

      const { access_token, user_id, username, role } = registerResponse.data;

      // Upload KYC document
      await api.post('/api/kyc/upload', {
        user_id,
        document_type: params.documentType || 'Aadhaar',
        document_data: params.governmentId,
      });

      // Login user
      await login(access_token, { user_id, username, role });

      Alert.alert(
        'Success',
        'Registration successful!',
        [{ text: 'OK', onPress: () => router.replace('/(user)/home') }]
      );
    } catch (error: any) {
      Alert.alert(
        'Error',
        error.response?.data?.detail || 'Registration failed'
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <TouchableOpacity 
        style={styles.backButton}
        onPress={() => router.back()}
      >
        <Ionicons name="arrow-back" size={24} color="#1f2937" />
      </TouchableOpacity>

      <View style={styles.content}>
        <View style={styles.header}>
          <Ionicons name="lock-closed" size={60} color="#6366f1" />
          <Text style={styles.title}>Verify OTP</Text>
          <Text style={styles.subtitle}>
            Enter the 6-digit code sent to{' \n'}
            {params.mobile}
          </Text>
          {params.mockOtp && (
            <Text style={styles.mockOtpText}>Mock OTP: {params.mockOtp}</Text>
          )}
        </View>

        <View style={styles.form}>
          <TextInput
            style={styles.otpInput}
            placeholder="Enter OTP"
            value={otp}
            onChangeText={setOtp}
            keyboardType="number-pad"
            maxLength={6}
            textAlign="center"
          />

          <TouchableOpacity
            style={[styles.verifyButton, loading && styles.verifyButtonDisabled]}
            onPress={handleVerifyAndRegister}
            disabled={loading}
          >
            {loading ? (
              <ActivityIndicator color="#ffffff" />
            ) : (
              <Text style={styles.verifyButtonText}>Verify & Register</Text>
            )}
          </TouchableOpacity>
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#ffffff',
    paddingHorizontal: 24,
  },
  backButton: {
    marginTop: 16,
  },
  content: {
    flex: 1,
    justifyContent: 'center',
  },
  header: {
    alignItems: 'center',
    marginBottom: 48,
  },
  title: {
    fontSize: 28,
    fontWeight: 'bold',
    color: '#1f2937',
    marginTop: 24,
  },
  subtitle: {
    fontSize: 16,
    color: '#6b7280',
    textAlign: 'center',
    marginTop: 8,
  },
  mockOtpText: {
    fontSize: 14,
    color: '#ef4444',
    fontWeight: '600',
    marginTop: 12,
    padding: 8,
    backgroundColor: '#fee2e2',
    borderRadius: 8,
  },
  form: {
    gap: 24,
  },
  otpInput: {
    borderWidth: 2,
    borderColor: '#6366f1',
    borderRadius: 12,
    paddingVertical: 20,
    fontSize: 24,
    fontWeight: '600',
    letterSpacing: 8,
  },
  verifyButton: {
    backgroundColor: '#6366f1',
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  verifyButtonDisabled: {
    opacity: 0.6,
  },
  verifyButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
});
