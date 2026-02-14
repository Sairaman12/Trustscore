import React, { useState, useEffect } from 'react';
import { 
  View, 
  Text, 
  StyleSheet, 
  ScrollView,
  TouchableOpacity,
  TextInput,
  Alert,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Image
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import api from '../../utils/api';

export default function UserDetails() {
  const router = useRouter();
  const { userId } = useLocalSearchParams();
  const [userData, setUserData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [score, setScore] = useState('');
  const [remarks, setRemarks] = useState('');

  useEffect(() => {
    fetchUserData();
  }, [userId]);

  const fetchUserData = async () => {
    try {
      const response = await api.get(`/api/admin/user/${userId}/complete-data`);
      setUserData(response.data);
      
      // Pre-fill if already scored
      if (response.data.trust_score?.admin_score) {
        setScore(response.data.trust_score.admin_score.toString());
        setRemarks(response.data.trust_score.remarks || '');
      }
    } catch (error) {
      console.error('Error fetching user data:', error);
      Alert.alert('Error', 'Failed to fetch user data');
    } finally {
      setLoading(false);
    }
  };

  const handleAssignScore = async () => {
    if (!score || parseInt(score) < 0 || parseInt(score) > 100) {
      Alert.alert('Error', 'Please enter a valid score (0-100)');
      return;
    }

    if (!remarks) {
      Alert.alert('Error', 'Please enter remarks');
      return;
    }

    Alert.alert(
      'Confirm',
      'Are you sure you want to assign this trust score? A PDF report will be generated and sent to the user via WhatsApp.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Confirm',
          onPress: async () => {
            setSubmitting(true);
            try {
              await api.post('/api/admin/assign-score', {
                user_id: userId,
                admin_score: parseInt(score),
                remarks,
              });

              Alert.alert(
                'Success',
                'Trust score assigned successfully! PDF report sent via WhatsApp (Mock).',
                [
                  {
                    text: 'OK',
                    onPress: () => router.back(),
                  },
                ]
              );
            } catch (error: any) {
              Alert.alert('Error', error.response?.data?.detail || 'Failed to assign score');
            } finally {
              setSubmitting(false);
            }
          },
        },
      ]
    );
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.container}>
        <ActivityIndicator size="large" color="#6366f1" />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <KeyboardAvoidingView 
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.keyboardView}
      >
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()}>
            <Ionicons name="arrow-back" size={24} color="#1f2937" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>User Details</Text>
          <View style={{ width: 24 }} />
        </View>

        <ScrollView contentContainerStyle={styles.scrollContent}>
          {/* User Info */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Personal Information</Text>
            <View style={styles.card}>
              <View style={styles.infoRow}>
                <Text style={styles.label}>Name:</Text>
                <Text style={styles.value}>{userData?.user?.username}</Text>
              </View>
              <View style={styles.infoRow}>
                <Text style={styles.label}>Email:</Text>
                <Text style={styles.value}>{userData?.user?.email}</Text>
              </View>
              <View style={styles.infoRow}>
                <Text style={styles.label}>Mobile:</Text>
                <Text style={styles.value}>{userData?.user?.mobile}</Text>
              </View>
              <View style={styles.infoRow}>
                <Text style={styles.label}>Age:</Text>
                <Text style={styles.value}>{userData?.user?.age} years</Text>
              </View>
            </View>
          </View>

          {/* KYC Document */}
          {userData?.kyc && (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>KYC Document</Text>
              <View style={styles.card}>
                <View style={styles.infoRow}>
                  <Text style={styles.label}>Document Type:</Text>
                  <Text style={styles.value}>{userData.kyc.document_type}</Text>
                </View>
                {userData.kyc.document_data && (
                  <View style={styles.documentPreview}>
                    <Image
                      source={{ uri: `data:image/jpeg;base64,${userData.kyc.document_data}` }}
                      style={styles.documentImage}
                      resizeMode="contain"
                    />
                  </View>
                )}
              </View>
            </View>
          )}

          {/* Income Details */}
          {userData?.income_details && (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>Income Details</Text>
              <View style={styles.card}>
                <View style={styles.infoRow}>
                  <Text style={styles.label}>Employment:</Text>
                  <Text style={styles.value}>{userData.income_details.employment_type}</Text>
                </View>
                <View style={styles.infoRow}>
                  <Text style={styles.label}>Income Type:</Text>
                  <Text style={styles.value}>{userData.income_details.income_type}</Text>
                </View>
                <View style={styles.infoRow}>
                  <Text style={styles.label}>Income Amount:</Text>
                  <Text style={styles.value}>₹{userData.income_details.income_amount}</Text>
                </View>
                <View style={styles.infoRow}>
                  <Text style={styles.label}>Monthly Expenses:</Text>
                  <Text style={styles.value}>₹{userData.income_details.monthly_expenses}</Text>
                </View>
              </View>
            </View>
          )}

          {/* Loan History */}
          {userData?.loan_history && (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>Loan History</Text>
              <View style={styles.card}>
                <View style={styles.infoRow}>
                  <Text style={styles.label}>Previous Loan:</Text>
                  <Text style={styles.value}>
                    {userData.loan_history.has_previous_loan ? 'Yes' : 'No'}
                  </Text>
                </View>
              </View>
            </View>
          )}

          {/* Bank Statements */}
          {userData?.bank_statements && userData.bank_statements.statements && (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>Bank Statements</Text>
              <View style={styles.card}>
                <Text style={styles.value}>
                  {userData.bank_statements.statements.length} document(s) uploaded
                </Text>
              </View>
            </View>
          )}

          {/* Assign Trust Score */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Assign Trust Score</Text>
            <View style={styles.card}>
              <View style={styles.inputGroup}>
                <Text style={styles.label}>Trust Score (0-100)</Text>
                <TextInput
                  style={styles.input}
                  placeholder="Enter score"
                  value={score}
                  onChangeText={setScore}
                  keyboardType="numeric"
                  maxLength={3}
                  editable={!submitting}
                />
              </View>

              <View style={styles.inputGroup}>
                <Text style={styles.label}>Remarks</Text>
                <TextInput
                  style={[styles.input, styles.textArea]}
                  placeholder="Enter evaluation remarks"
                  value={remarks}
                  onChangeText={setRemarks}
                  multiline
                  numberOfLines={4}
                  textAlignVertical="top"
                  editable={!submitting}
                />
              </View>

              <TouchableOpacity
                style={[styles.submitButton, submitting && styles.submitButtonDisabled]}
                onPress={handleAssignScore}
                disabled={submitting}
              >
                {submitting ? (
                  <ActivityIndicator color="#ffffff" />
                ) : (
                  <>
                    <Ionicons name="checkmark-circle" size={20} color="#ffffff" />
                    <Text style={styles.submitButtonText}>Assign Score & Send Report</Text>
                  </>
                )}
              </TouchableOpacity>

              {userData?.trust_score?.status === 'completed' && (
                <View style={styles.successMessage}>
                  <Ionicons name="checkmark-circle" size={20} color="#10b981" />
                  <Text style={styles.successText}>
                    Score already assigned and report sent
                  </Text>
                </View>
              )}
            </View>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f9fafb',
  },
  keyboardView: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingVertical: 16,
    backgroundColor: '#ffffff',
    borderBottomWidth: 1,
    borderBottomColor: '#f3f4f6',
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#1f2937',
  },
  scrollContent: {
    padding: 20,
  },
  section: {
    marginBottom: 24,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#1f2937',
    marginBottom: 12,
  },
  card: {
    backgroundColor: '#ffffff',
    borderRadius: 12,
    padding: 16,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
  },
  infoRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  label: {
    fontSize: 14,
    fontWeight: '600',
    color: '#6b7280',
  },
  value: {
    fontSize: 14,
    color: '#1f2937',
    flex: 1,
    textAlign: 'right',
  },
  documentPreview: {
    marginTop: 12,
    borderRadius: 8,
    overflow: 'hidden',
  },
  documentImage: {
    width: '100%',
    height: 200,
  },
  inputGroup: {
    marginBottom: 16,
  },
  input: {
    borderWidth: 1,
    borderColor: '#d1d5db',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 14,
    marginTop: 8,
  },
  textArea: {
    minHeight: 100,
  },
  submitButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    backgroundColor: '#6366f1',
    paddingVertical: 14,
    borderRadius: 8,
    marginTop: 8,
  },
  submitButtonDisabled: {
    opacity: 0.6,
  },
  submitButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
  successMessage: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginTop: 16,
    padding: 12,
    backgroundColor: '#d1fae5',
    borderRadius: 8,
  },
  successText: {
    fontSize: 14,
    color: '#10b981',
    fontWeight: '500',
  },
});
